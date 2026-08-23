"""Gabungin row Player/Team duplikat yang telanjur kebikin sebelum matcher
nama diperbaiki (aksen nggak dilipat — 'Šeško' vs 'Sesko' ke-anggep 2 orang).

Default-nya DRY RUN: nggak nulis apa-apa, cuma nampilin rencananya. Harus
lewat --apply buat beneran ngubah data.

    python manage.py merge_duplicates                # lihat rencananya
    python manage.py merge_duplicates --apply        # eksekusi

Referensi FK di-enumerate dinamis dari _meta, bukan di-hardcode: mayoritas
FK ke Team itu CASCADE, jadi satu referensi kelewat = Match ikut kehapus pas
row duplikatnya dibuang.
"""

from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand

from players.merge_utils import absorb
from players.models import DataSource, Player, Team
from players.provenance import resolve_updates
from players.name_utils import fold_accents, normalize_team_name


def player_group_key(player):
    """Kunci pengelompokan: (inisial depan, nama belakang) yang udah dilipat
    aksennya — persis logika player_identity_key, tapi dipanggil di sini biar
    jelas apa yang dijadiin dasar penggabungan."""
    words = [w for w in fold_accents(player.name).replace('.', ' ').split() if w]
    if not words:
        return None
    initial = words[0][0] if len(words) > 1 else ''
    return initial, words[-1]


class Command(BaseCommand):
    help = 'Gabungin Player/Team duplikat hasil bug pencocokan nama beraksen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Beneran tulis perubahan. Tanpa ini cuma dry run.',
        )
        parser.add_argument('--players-only', action='store_true')
        parser.add_argument('--teams-only', action='store_true')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        do_teams = not options['players_only']
        do_players = not options['teams_only']

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING('DRY RUN — nggak ada yang ditulis. Tambahin --apply buat eksekusi.\n')
            )

        total = 0
        # Tim duluan: kalau 2 tim digabung, pemainnya pindah ke tim yang sama
        # dan baru kedeteksi sebagai duplikat di tahap pemain.
        if do_teams:
            total += self._merge_teams(apply_changes)
            # Harus SESUDAH tim digabung: dua record tim untuk satu klub bikin
            # satu laga tersimpan dua kali, dan itu baru kelihatan setelah
            # keduanya menunjuk tim yang sama.
            total += self._merge_duplicate_matches(apply_changes)
        if do_players:
            total += self._merge_players(apply_changes)
            total += self._merge_co_occurring(apply_changes)
            total += self._merge_roster_leftovers(apply_changes)
            total += self._merge_transfers(apply_changes)
            total += self._merge_understat_aliases(apply_changes)

        if not total:
            self.stdout.write(self.style.SUCCESS('Nggak ada duplikat. Nggak ada yang perlu digabung.'))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f'\nSelesai. {total} row duplikat digabung.'))
        else:
            self.stdout.write(
                self.style.WARNING(f'\n{total} row bakal digabung. Jalanin ulang pakai --apply.')
            )

    # ------------------------------------------------------------------ teams

    def _merge_teams(self, apply_changes):
        groups = defaultdict(list)
        for team in Team.objects.all():
            key = normalize_team_name(team.name)
            if key:
                groups[key].append(team)

        merged = 0
        for key, teams in sorted(groups.items()):
            if len(teams) < 2:
                continue
            canonical, losers = self._pick_canonical(teams)
            self.stdout.write(f'TIM  {canonical.name!r} (id={canonical.pk})')
            for loser in losers:
                self.stdout.write(f'       <- {loser.name!r} (id={loser.pk})')
                if apply_changes:
                    self._absorb(loser, canonical)
                merged += 1
        return merged

    # ---------------------------------------------------------------- players

    def _merge_duplicate_matches(self, apply_changes):
        """Lebur Match yang sebenarnya satu laga: tim sama, tanggal sama.

        Muncul sebagai efek samping penggabungan tim. Highlightly menyebut klub
        itu 'Wolves' dan provider lain 'Wolverhampton Wanderers', jadi tiap
        pertemuan tersimpan dua kali di bawah dua record tim. Begitu timnya
        digabung, keduanya menunjuk tim yang sama dan barulah terlihat kembar.

        Dampaknya bukan kosmetik: Premier League tercatat **40 laga per musim**
        padahal 38, jadi filter kompetisi apa pun yang dibangun di atasnya akan
        salah hitung.

        **Event wajib di-dedup dulu.** MatchEvent tidak punya unique constraint,
        jadi memindahkan begitu saja akan menggandakan gol dan kartu — laga
        1-0 mendadak punya dua gol yang sama. Kembaran yang statistiknya kosong
        pun biasanya tetap membawa 15-23 event dari provider lain.
        """
        Match = apps.get_model('matches', 'Match')
        MatchEvent = apps.get_model('matches', 'MatchEvent')

        kelompok = defaultdict(list)
        for m in Match.objects.select_related('home_team', 'away_team'):
            kelompok[(m.home_team_id, m.away_team_id, m.kickoff_at.date())].append(m)

        merged = 0
        for kunci, laga in sorted(kelompok.items(), key=lambda kv: str(kv[0])):
            if len(laga) < 2:
                continue

            def bobot(m):
                return (
                    m.player_statistics.count()
                    + m.plays.count()
                    + m.shots.count()
                    + m.events.count()
                )

            urut = sorted(laga, key=lambda m: (-bobot(m), m.pk))
            canonical, losers = urut[0], urut[1:]
            self.stdout.write(
                f'LAGA GANDA #{canonical.pk} {canonical.home_team.name[:16]} vs '
                f'{canonical.away_team.name[:16]} {canonical.kickoff_at:%Y-%m-%d} '
                f'(isi {bobot(canonical)}) <- '
                + ', '.join(f'{m.pk}(isi {bobot(m)})' for m in losers)
            )

            if apply_changes:
                for loser in losers:
                    self._dedup_events(canonical, loser, MatchEvent)
                    absorb(loser, canonical)
            merged += len(losers)

        return merged

    @staticmethod
    def _dedup_events(canonical, loser, MatchEvent):
        """Buang event `loser` yang sudah punya padanan di `canonical`.

        Padanan = jenis, menit, tim, dan pemain yang sama. Tanpa ini gol yang
        sama tercatat dua kali setelah penggabungan.
        """
        sudah = {
            (e.event_type, e.minute, e.team_id, e.player_id)
            for e in MatchEvent.objects.filter(match=canonical)
        }
        for e in MatchEvent.objects.filter(match=loser):
            if (e.event_type, e.minute, e.team_id, e.player_id) in sudah:
                e.delete()

    def _merge_players(self, apply_changes):
        groups = defaultdict(list)
        skipped_no_team = 0
        for player in Player.objects.select_related('team'):
            key = player_group_key(player)
            if key is None:
                continue
            if player.team_id is None:
                # Sengaja nggak digabung: tanpa tim, 2 pemain beda klub yang
                # kebetulan senama bisa ketuker. Sama batasannya kayak
                # resolve_player yang selalu nyaring per tim.
                skipped_no_team += 1
                continue
            groups[(player.team_id, key)].append(player)

        merged = 0
        for (team_id, key), players in sorted(groups.items(), key=lambda x: str(x[0])):
            if len(players) < 2:
                continue
            canonical, losers = self._pick_canonical(players)
            self.stdout.write(
                f'PEMAIN {canonical.name!r} (id={canonical.pk}, tim={canonical.team})'
            )
            for loser in losers:
                self.stdout.write(f'         <- {loser.name!r} (id={loser.pk})')
                if apply_changes:
                    self._absorb(loser, canonical)
                merged += 1

        if skipped_no_team:
            self.stdout.write(
                self.style.WARNING(
                    f'\n{skipped_no_team} pemain tanpa tim dilewati (nggak aman digabung '
                    f'tanpa tim sebagai penyaring).'
                )
            )
        return merged

    # ------------------------------------------------- muncul di laga yang sama

    def _merge_co_occurring(self, apply_changes):
        """Gabungin Player yang punya statistik di laga DAN tim yang sama.

        Dua orang berbeda nggak mungkin dua-duanya main di satu laga untuk satu
        tim dengan nama yang sama. Jadi ini bukti identitas yang jauh lebih kuat
        daripada nama + tim saat ini.

        Perlu jalur sendiri karena _merge_players nyaring per Player.team, dan
        pasangan begini justru punya Player.team BERBEDA — tiap record terakhir
        disentuh provider yang beda, dan tiap provider nyebut tim yang beda
        (pemain baru pindah, atau sisa bug atribusi tim yang lama).
        """
        from django.db.models import Count

        from matches.models import PlayerMatchStatistics

        groups = (
            PlayerMatchStatistics.objects.values('match_id', 'team_id', 'player__name')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )

        merged = 0
        handled = set()
        for group in groups:
            rows = list(
                PlayerMatchStatistics.objects.filter(
                    match_id=group['match_id'],
                    team_id=group['team_id'],
                    player__name=group['player__name'],
                ).select_related('player')
            )
            players = {r.player_id: r.player for r in rows}
            if len(players) < 2:
                continue

            key = tuple(sorted(players))
            if key in handled:
                continue
            handled.add(key)

            canonical, losers = self._pick_canonical(list(players.values()))
            self.stdout.write(
                f'SATU LAGA {canonical.name!r} (id={canonical.pk}) '
                f'<- {", ".join(str(l.pk) for l in losers)}'
            )
            if apply_changes:
                for loser in losers:
                    self._merge_stat_rows(canonical, loser)
                    absorb(loser, canonical)
            merged += len(losers)

        return merged

    def _merge_roster_leftovers(self, apply_changes):
        """Gabungin sisa roster: record tanpa statistik yang kembar dengan
        record bermain-beneran, di tim yang berbeda.

        Asalnya dari `pull_match_events_pl`, yang bikin Player untuk seluruh
        skuad Premier League. Waktu pemainnya pindah klub, provider lain
        (ESPN/FotMob) mencatatnya di klub baru — dan karena `resolve_player`
        mencocokkan nama HANYA dalam satu tim, lahirlah record kedua. Yang lama
        tertinggal tanpa pernah dapat satu pun baris statistik.

        Sekarang belum ada data yang rusak: statistiknya semua menumpuk di satu
        record. Yang diperbaiki di sini justru yang akan datang — selama dua
        record itu hidup, `pull_match_events_pl` akan terus menaruh statistik di
        record lama (dia resolve lewat premier_league id) sementara ESPN dan
        FotMob menaruhnya di record baru. Begitu pemainnya main lagi, statistik
        satu orang terbelah dua.

        Dua pengaman, dan keduanya harus lolos:

        1. **Tepat satu record punya statistik.** Kalau dua-duanya punya, ini
           bukan sisa roster dan butuh penilaian lain. Kalau tak satu pun punya,
           tidak ada bukti apa pun untuk menyatukan mereka.
        2. **Tidak ada provider yang memegang dua record sekaligus.** Kalau
           FotMob (atau Premier League) menerbitkan dua id berbeda untuk nama
           yang sama, provider itu sendiri menyatakan mereka dua orang berbeda —
           dan memang ada dua Ben Johnson, dua Josh King. Itu bukti yang lebih
           kuat daripada kemiripan nama, jadi grup begitu dilewati.
        3. **Nama lengkapnya harus identik.** Kunci pengelompokan cuma
           (inisial, nama belakang) — cukup untuk aturan per-tim, tapi terlalu
           longgar begitu penggabungan melintasi tim: 'Adam Armstrong' dan
           'Aaron Armstrong' punya kunci yang sama persis. Di dalam satu tim
           tabrakan begitu praktis mustahil; di seluruh liga tidak.
        """
        from matches.models import PlayerMatchStatistics

        groups = defaultdict(list)
        for player in Player.objects.select_related('team'):
            groups[player_group_key(player)].append(player)

        merged = 0
        for key, players in sorted(groups.items()):
            if len(players) < 2 or not key:
                continue

            # Pengaman 2 — provider yang menerbitkan dua id untuk grup ini
            # menganggap mereka orang berbeda.
            per_source = defaultdict(set)
            for player in players:
                for ref in player.external_refs.all():
                    per_source[ref.source].add(player.pk)
            pembeda = sorted(src for src, pks in per_source.items() if len(pks) > 1)
            if pembeda:
                self.stdout.write(
                    f'  lewati {players[0].name!r} — {"/".join(pembeda)} '
                    f'menerbitkan id berbeda, kemungkinan besar dua orang'
                )
                continue

            # Pengaman 3 — nama lengkap harus sama persis, bukan cuma
            # inisial + nama belakang.
            if len({fold_accents(p.name) for p in players}) > 1:
                continue

            # Pengaman 1 — tepat satu record yang punya statistik.
            berstatistik = [
                p for p in players
                if PlayerMatchStatistics.objects.filter(player=p).exists()
            ]
            if len(berstatistik) != 1:
                continue

            # Yang dipertahankan BUKAN otomatis yang punya statistik.
            #
            # Karl Darlow terdaftar di skuad MU (record aktif dari
            # `pull_squad`), tapi seluruh statistiknya dari masa Leeds. Memilih
            # kanonik semata-mata dari "siapa yang punya statistik" akan
            # menghapusnya dari skuad MU.
            #
            # Tapi "ada di MU" saja tidak cukup, dan ini pelajaran mahal:
            # parser komentar ESPN sempat salah-atribusi pemain lawan ke MU,
            # meninggalkan record hantu — non-aktif, nol statistik, dan
            # satu-satunya sumbernya `espn_commentary`. Ademola Lookman,
            # Calvert-Lewin, Daniel James, dan Jayden Bogle semuanya punya
            # record MU semacam itu padahal tidak pernah membela MU. Aturan
            # "MU menang" yang naif justru menjadikan hantu itu kanonik.
            #
            # Jadi syaratnya diperketat: harus MU, harus `is_active`, dan harus
            # punya sumber selain komentar. Jadon Sancho lolos saringan ini
            # dengan benar — record MU-nya non-aktif karena dia sudah pindah,
            # jadi yang menang record Aston Villa yang punya 23 laga.
            #
            # Statistiknya tetap ikut pindah, dan atribusi tim per laga aman
            # karena tiap baris PlayerMatchStatistics simpan `team` sendiri.
            skuad_mu = [
                p for p in players
                if p.team and p.team.is_manchester_united
                and p.is_active
                and any(r.source != DataSource.ESPN_COMMENTARY for r in p.external_refs.all())
            ]
            canonical = skuad_mu[0] if skuad_mu else berstatistik[0]
            losers = [p for p in players if p.pk != canonical.pk]
            self.stdout.write(
                f'SISA ROSTER {canonical.name!r} (id={canonical.pk}, '
                f'{canonical.team.name if canonical.team else "-"}) <- '
                + ', '.join(
                    f'{l.pk}@{l.team.name if l.team else "-"}' for l in losers
                )
            )
            if apply_changes:
                for loser in losers:
                    absorb(loser, canonical)
            merged += len(losers)

        return merged

    def _merge_transfers(self, apply_changes):
        """Gabungin pemain yang statistiknya TERBELAH dua record karena transfer.

        Ini yang paling merusak analisis: James Ward-Prowse punya 12 laga di
        record West Ham dan 18 di record Burnley, jadi tolok ukur se-liga
        membaca dia sebagai dua pemain setengah-musim, bukan satu pemain penuh.
        Berbeda dari sisa roster, DUA-DUANYA punya statistik — jadi aturan itu
        sengaja melewatinya, dan butuh bukti yang lebih kuat.

        Buktinya: **tidak boleh ada satu tanggal pun yang muncul di dua record.**
        Satu orang tidak bisa membela dua klub di hari yang sama. Kalau
        tanggalnya terpisah bersih, itu pola transfer; kalau ada yang bentrok,
        itu dua orang berbeda dan grupnya dilewati.

        Waktu aturan ini ditulis, 15 grup lolos dan tidak satu pun punya tanggal
        bentrok — semuanya transfer beneran (Kudus West Ham -> Tottenham,
        Zinchenko Arsenal -> Forest, Nørgaard Brentford -> Arsenal).

        Kanoniknya record dengan penampilan TERAKHIR, yaitu klub dia sekarang —
        kecuali salah satunya record skuad MU yang aktif, aturan yang sama
        seperti di _merge_roster_leftovers.
        """
        from matches.models import PlayerMatchStatistics

        groups = defaultdict(list)
        for player in Player.objects.select_related('team'):
            groups[player_group_key(player)].append(player)

        merged = 0
        for key, players in sorted(groups.items()):
            if len(players) < 2 or not key:
                continue
            if len({fold_accents(p.name) for p in players}) > 1:
                continue

            per_source = defaultdict(set)
            for player in players:
                for ref in player.external_refs.all():
                    per_source[ref.source].add(player.pk)
            if any(len(pks) > 1 for pks in per_source.values()):
                continue

            tanggal = {}
            for player in players:
                hari = {
                    row.match.kickoff_at.date()
                    for row in PlayerMatchStatistics.objects.filter(
                        player=player
                    ).select_related('match')
                }
                if hari:
                    tanggal[player.pk] = hari
            if len(tanggal) < 2:
                continue  # urusan _merge_roster_leftovers, bukan di sini

            # Satu tanggal yang muncul di dua record = dua orang berbeda.
            pks = list(tanggal)
            bentrok = any(
                tanggal[pks[i]] & tanggal[pks[j]]
                for i in range(len(pks))
                for j in range(i + 1, len(pks))
            )
            if bentrok:
                self.stdout.write(
                    f'  lewati {players[0].name!r} — main di tanggal yang sama '
                    f'untuk klub berbeda, jadi dua orang'
                )
                continue

            skuad_mu = [
                p for p in players
                if p.team and p.team.is_manchester_united
                and p.is_active
                and any(r.source != DataSource.ESPN_COMMENTARY for r in p.external_refs.all())
            ]
            if skuad_mu:
                canonical = skuad_mu[0]
            else:
                # Penampilan terakhir = klub dia sekarang.
                canonical = max(tanggal, key=lambda pk: max(tanggal[pk]))
                canonical = next(p for p in players if p.pk == canonical)

            losers = [p for p in players if p.pk != canonical.pk]
            self.stdout.write(
                f'TRANSFER {canonical.name!r} (id={canonical.pk}, '
                f'{canonical.team.name if canonical.team else "-"}) <- '
                + ', '.join(f'{l.pk}@{l.team.name if l.team else "-"}' for l in losers)
            )
            if apply_changes:
                for loser in losers:
                    self._merge_stat_rows(canonical, loser)
                    absorb(loser, canonical)
            merged += len(losers)

        return merged

    def _merge_understat_aliases(self, apply_changes):
        """Gabungin record yang lahir karena Understat menulis nama lebih panjang.

        Understat memakai nama lengkap sementara provider lain memakai nama
        panggung: 'Amad Diallo Traore' vs 'Amad Diallo', 'Ezri Konsa Ngoyo' vs
        'Ezri Konsa', 'Iyenoma Destiny Udogie' vs 'Destiny Udogie'. Kunci
        pencocokan yang ada cuma (inisial, nama belakang), jadi 'diallo' vs
        'traore' dibaca sebagai dua orang.

        Akibatnya di produksi: Amad Diallo punya 146 laga di satu record dan 32
        di record lain. Aturan lain tidak menjangkaunya — `_merge_co_occurring`
        menuntut nama yang sama persis, `_merge_transfers` menuntut tanggal
        yang terpisah padahal ini justru bertumpuk.

        Tiga syarat, semuanya harus lolos:

        1. Record itu HANYA bersumber `understat`. Kalau provider lain juga
           mengenalnya, dia entitas yang berdiri sendiri.
        2. Tepat SATU kandidat di tim yang sama yang token namanya himpunan
           bagian atau sama persis. Nottingham Forest punya 'Jair Cunha' DAN
           'Jair Paula' — nama 'Jair' saja tidak boleh dipaksa memilih.
        3. Mereka pernah muncul di laga DAN tim yang sama. Itu bukti
           pemecahannya nyata, bukan sekadar nama mirip.

        Yang sengaja TIDAK tertangkap dan memang harus dibiarkan: 'Yehor
        Yarmolyuk' vs 'Yehor Yarmoliuk' (beda transliterasi, bukan himpunan
        bagian) dan 'Chimuanya Ugochukwu' vs 'Lesley Ugochukwu' (beda nama
        depan). Keduanya butuh mata manusia.
        """
        import html as _html

        from matches.models import PlayerMatchStatistics
        from players.models import PlayerExternalRef

        def token(nama):
            return {t for t in fold_accents(_html.unescape(nama)).replace('-', ' ').split() if t}

        sumber = defaultdict(set)
        for ref in PlayerExternalRef.objects.all():
            sumber[ref.player_id].add(ref.source)
        hanya_understat = [pid for pid, s in sumber.items() if s == {DataSource.UNDERSTAT}]

        merged = 0
        for loser in Player.objects.filter(pk__in=hanya_understat).select_related('team'):
            if loser.team_id is None:
                continue
            target = token(loser.name)
            if len(target) < 2:
                continue  # nama satu kata terlalu lemah

            cocok = [
                p for p in Player.objects.filter(team_id=loser.team_id).exclude(pk=loser.pk)
                if (lambda t: bool(t) and (t <= target or target <= t))(token(p.name))
            ]
            if len(cocok) != 1:
                if len(cocok) > 1:
                    self.stdout.write(
                        f'  lewati {loser.name!r} — {len(cocok)} kandidat, ambigu'
                    )
                continue

            canonical = cocok[0]
            laga_loser = set(
                PlayerMatchStatistics.objects.filter(player=loser).values_list('match_id', flat=True)
            )
            laga_canon = set(
                PlayerMatchStatistics.objects.filter(player=canonical).values_list('match_id', flat=True)
            )
            bareng = laga_loser & laga_canon
            if not bareng:
                self.stdout.write(
                    f'  lewati {loser.name!r} — tidak pernah muncul di laga yang sama '
                    f'dengan {canonical.name!r}, buktinya kurang'
                )
                continue

            self.stdout.write(
                f'ALIAS UNDERSTAT {canonical.name!r} (id={canonical.pk}, '
                f'{len(laga_canon)} laga) <- {loser.pk} {loser.name!r} '
                f'({len(laga_loser)} laga, {len(bareng)} bertumpuk)'
            )
            if apply_changes:
                # Baris statistik disatukan DULU. Tanpa ini absorb() membuang
                # baris loser karena bentrok unique(match, player) — dan isinya
                # ikut hilang, padahal justru di situ kolom xG-nya.
                self._merge_stat_rows(canonical, loser)
                absorb(loser, canonical)
            merged += 1

        return merged

    @staticmethod
    def _merge_stat_rows(canonical, loser):
        """Satukan isi baris statistik sebelum row-nya dibuang.

        Tanpa ini, absorb() bakal ngehapus baris `loser` karena bentrok unique
        (match, player) — dan isinya ikut hilang. Padahal justru di situ
        masalahnya: satu record punya xG dari Understat, satunya punya sentuhan
        dari FotMob. Yang dipertahankan harus gabungan keduanya, bukan salah
        satunya.
        """
        from matches.models import PlayerMatchStatistics

        skip = {'id', 'match', 'player', 'team', 'field_sources', 'updated_at'}
        for lose_row in PlayerMatchStatistics.objects.filter(player=loser):
            keep_row = PlayerMatchStatistics.objects.filter(
                match=lose_row.match, player=canonical
            ).first()
            if keep_row is None:
                continue

            values, sources = {}, dict(lose_row.field_sources or {})
            for field in PlayerMatchStatistics._meta.fields:
                if field.name in skip:
                    continue
                value = getattr(lose_row, field.name)
                if value is None:
                    continue
                values[field.name] = value

            # Tiap field dibawa berikut sumber aslinya, jadi prioritas provider
            # tetap berlaku waktu digabung.
            for field, value in values.items():
                source = sources.get(field)
                if source is None:
                    continue
                updates, merged_sources = resolve_updates(
                    keep_row.field_sources, source, {field: value}
                )
                if updates:
                    updates['field_sources'] = merged_sources
                    PlayerMatchStatistics.objects.filter(pk=keep_row.pk).update(**updates)
                    keep_row.refresh_from_db()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _pick_canonical(candidates):
        """Yang dipertahanin: paling banyak external ref (paling nyambung ke
        provider), lalu paling lengkap datanya, lalu pk terkecil biar hasilnya
        stabil kalau command-nya dijalanin ulang."""

        def score(obj):
            refs = obj.external_refs.count()
            filled = sum(
                1
                for field in obj._meta.fields
                if field.name not in ('id', 'created_at', 'updated_at')
                and getattr(obj, field.attname, None) not in (None, '', False)
            )
            return (-refs, -filled, obj.pk)

        ordered = sorted(candidates, key=score)
        return ordered[0], ordered[1:]

    def _absorb(self, loser, canonical):
        is_team = isinstance(loser, Team)
        absorb(loser, canonical)
        if is_team:
            self._drop_self_matches(canonical)

    @staticmethod
    def _drop_self_matches(canonical):
        """Kalau 2 tim yang digabung pernah ketemu satu sama lain, hasil
        penggabungannya jadi match lawan diri sendiri — itu artefak duplikasi,
        bukan pertandingan beneran."""
        Match = apps.get_model('matches', 'Match')
        Match.objects.filter(home_team=canonical, away_team=canonical).delete()
