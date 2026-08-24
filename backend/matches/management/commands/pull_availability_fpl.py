"""Status ketersediaan pemain MU dari Fantasy Premier League.

**Kenapa FPL.** Sampai sekarang cuma Highlightly yang jadi sumber cedera, jadi
panel Konflik Sumber di desain nggak pernah bisa terisi — nggak ada yang bisa
berselisih. Dan Highlightly ternyata bukan feed ketersediaan sama sekali: dia
RIWAYAT KARIER, entri terbaru Mason Mount berakhir September 2021. Itu yang
bikin 263 dari 264 entri MU berstatus RETURNED.

FPL ngasih ketiga hal yang diminta desain sekaligus, dalam SATU panggilan HTTP
tanpa API key: status, teks prognosis, dan **umur data** lewat `news_added`.

**Catatan sah-pakai.** Endpoint ini publik, tanpa key, dan disajikan lewat CDN
buat konsumsi anonim — tapi ToU Premier League membatasi pemakaian ke keperluan
pribadi/non-komersial. App ini internal komunitas dan non-komersial, dan repo
ini sudah memakai Premier League/PulseLive lewat `pull_match_events_pl` di
bawah ToU yang sama. Jadi ini bukan kategori risiko baru.

**Cakupannya 33 dari 38 pemain**, bukan semua. Pemain yang nggak didaftarkan di
skuad Premier League nggak muncul. Buat mereka statusnya ditulis
'tidak dicakup sumber' — BUKAN 'bugar'. Diam-diam menganggap mereka bugar itu
persis jenis kesalahan yang bikin panel ini nggak bisa dipercaya.
"""

from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.models import SourceHeartbeat
from players.models import DataSource, Player, PlayerAvailability

URL = 'https://fantasy.premierleague.com/api/bootstrap-static/'
TIMEOUT = 30

# Kode status FPL -> status kita.
#   a = available, d = doubtful, i = injured, s = suspended,
#   u = unavailable (pindah/dipinjamkan), n = not in squad
PETA_STATUS = {
    'a': PlayerAvailability.Status.FIT,
    'd': PlayerAvailability.Status.DOUBTFUL,
    'i': PlayerAvailability.Status.OUT,
    's': PlayerAvailability.Status.SUSPENDED,
    'u': PlayerAvailability.Status.LOANED,
    'n': PlayerAvailability.Status.UNKNOWN,
}


class Command(BaseCommand):
    help = 'Narik status ketersediaan pemain MU dari Fantasy Premier League.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-name', default='Man Utd',
            help="Nama tim MU di FPL (default 'Man Utd').",
        )

    def handle(self, *args, **options):
        try:
            response = requests.get(URL, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f'Gagal narik FPL: {exc}') from exc

        tim = [
            t for t in payload.get('teams') or []
            if options['team_name'].lower() in (t.get('name') or '').lower()
        ]
        if not tim:
            raise CommandError(
                f"Tim {options['team_name']!r} nggak ketemu di daftar FPL. "
                f"Nama yang ada: {[t['name'] for t in payload.get('teams') or []]}"
            )
        team_id = tim[0]['id']

        entri = [p for p in payload.get('elements') or [] if p.get('team') == team_id]
        self.stdout.write(f'{len(entri)} pemain MU di FPL')

        from players.models import Team

        mu = Team.objects.filter(is_manchester_united=True).first()
        if mu is None:
            raise CommandError('Nggak ada Team bertanda is_manchester_united.')

        skuad = list(Player.objects.filter(team=mu, is_active=True))
        tersentuh, bermasalah, tak_ketemu = set(), 0, []

        for e in entri:
            player = self._cocokkan(e, skuad)
            if player is None:
                tak_ketemu.append(f"{e.get('first_name')} {e.get('second_name')}")
                continue

            status = PETA_STATUS.get(e.get('status'), PlayerAvailability.Status.UNKNOWN)
            PlayerAvailability.objects.update_or_create(
                player=player,
                source=DataSource.FPL,
                defaults={
                    'status': status,
                    'note': (e.get('news') or '')[:255],
                    'chance_pct': e.get('chance_of_playing_next_round'),
                    'source_updated_at': self._waktu(e.get('news_added')),
                },
            )
            tersentuh.add(player.pk)
            if status not in (
                PlayerAvailability.Status.FIT, PlayerAvailability.Status.UNKNOWN
            ):
                bermasalah += 1
                self.stdout.write(
                    f"  [{status}] {player.name}: {(e.get('news') or '-')[:56]}"
                )

        # Pemain skuad yang FPL nggak cakup. Ditulis eksplisit sebagai
        # 'tidak dicakup', bukan dibiarkan kosong — panel Konflik harus bisa
        # membedakan "sumbernya bilang bugar" dari "sumbernya nggak tahu".
        luar = [p for p in skuad if p.pk not in tersentuh]
        for p in luar:
            PlayerAvailability.objects.update_or_create(
                player=p,
                source=DataSource.FPL,
                defaults={
                    'status': PlayerAvailability.Status.UNKNOWN,
                    'note': 'Nggak terdaftar di skuad Premier League menurut FPL',
                    'chance_pct': None,
                    'source_updated_at': None,
                },
            )

        SourceHeartbeat.objects.update_or_create(
            source=DataSource.FPL,
            defaults={'note': f'{len(tersentuh)} pemain cocok, {bermasalah} bermasalah'},
        )

        if tak_ketemu:
            self.stdout.write(
                self.style.WARNING(
                    f'{len(tak_ketemu)} entri FPL nggak ketemu padanannya di skuad: '
                    f'{", ".join(tak_ketemu[:5])}'
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(tersentuh)} pemain diperbarui, {bermasalah} bermasalah, '
                f'{len(luar)} ditandai tidak dicakup.'
            )
        )

    @staticmethod
    def _cocokkan(entri, skuad):
        """Cocokin entri FPL ke Player.

        FPL nulis nama lengkap resmi ('Matheus Santos Carneiro da Cunha')
        sementara DB kita nyimpen nama umum ('Matheus Cunha'), jadi pencocokan
        nama utuh sering meleset. `player_names_match` udah menangani ini lewat
        inisial + nama belakang dengan aksen dilipat.
        """
        from players.name_utils import player_names_match

        kandidat = [
            f"{entri.get('first_name', '')} {entri.get('second_name', '')}".strip(),
            entri.get('web_name') or '',
        ]
        for nama in kandidat:
            if not nama:
                continue
            for p in skuad:
                if player_names_match(p.name, nama):
                    return p
        return None

    @staticmethod
    def _waktu(teks):
        """news_added FPL: ISO8601 presisi mikrodetik berakhiran Z."""
        if not teks:
            return None
        try:
            return datetime.fromisoformat(teks.replace('Z', '+00:00'))
        except ValueError:
            return None
