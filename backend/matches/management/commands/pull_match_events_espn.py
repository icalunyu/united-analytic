import re
import zlib
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.dedup import resolve_match
from matches.ingest_utils import store_raw
from matches.models import (
    Match,
    MatchEvent,
    MatchIngest,
    MatchPlay,
    MatchTeamStatistics,
    PlayerMatchStatistics,
)
from matches.services import EspnClient, EspnError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource
from players.name_utils import team_names_match
from players.provenance import resolve_updates


def _stable_id(name):
    """ID pseudo-stabil buat pemain yang cuma ketemu lewat teks commentary
    (nggak ada athlete id numerik kayak di keyEvents)."""
    return zlib.crc32(name.strip().lower().encode()) & 0x7FFFFFFF

SLUG_LABELS = {
    'eng.1': 'Premier League',
    'eng.fa': 'FA Cup',
    'eng.league_cup': 'League Cup',
    'uefa.champions': 'UEFA Champions League',
    'uefa.europa': 'UEFA Europa League',
    'uefa.europa.conf': 'UEFA Conference League',
    'eng.charity': 'Community Shield',
    'club.friendly': 'Club Friendly',
}


def _map_status(status_type):
    """ESPN punya banyak varian `name` (STATUS_FIRST_HALF, STATUS_SECOND_HALF,
    dll) buat match yang lagi jalan — lebih aman ngandelin `state` yang cuma
    3 nilai (pre/in/post), `name` cuma buat kasus khusus (halftime/postponed/
    cancelled)."""
    name = (status_type or {}).get('name', '')
    state = (status_type or {}).get('state', '')

    if 'POSTPONED' in name:
        return Match.Status.POSTPONED
    if 'CANCEL' in name or 'ABANDON' in name:
        return Match.Status.CANCELLED
    if state == 'pre':
        return Match.Status.NOT_STARTED
    if state == 'post':
        return Match.Status.FINISHED
    if 'HALFTIME' in name:
        return Match.Status.HALFTIME
    return Match.Status.LIVE


class Command(BaseCommand):
    help = (
        'Narik jadwal + match events (gol/kartu/substitusi) MU dari ESPN '
        '(API internal situs mereka, tidak resmi didukung pihak ketiga), '
        'simpan/update ke database.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=str, default=None, help='Override ESPN_MU_TEAM_ID dari settings'
        )
        parser.add_argument('--season', type=int, default=None, help='Contoh: 2025')
        parser.add_argument(
            '--slug',
            type=str,
            default=None,
            help='Cuma 1 kompetisi (mis. eng.fa). Default: semua slug di ESPN_COMPETITION_SLUGS.',
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.ESPN_MU_TEAM_ID
        client = EspnClient()

        # NB: kompetisi liga (eng.1) butuh --season eksplisit buat dapet data
        # (nggak ada default yang selalu bener — musim baru belum tentu udah
        # ke-publish di ESPN pas awal Juli). Kompetisi cup/friendly biasanya
        # justru lebih lengkap TANPA season (nunjukin next/last apa adanya).
        season = options['season']

        slugs = (
            [options['slug']]
            if options['slug']
            else [s.strip() for s in settings.ESPN_COMPETITION_SLUGS.split(',') if s.strip()]
        )

        processed = 0
        events_total = 0
        plays_total = 0
        players_total = 0
        fixtures_total = 0
        seen_ids = set()

        today = timezone.now().strftime('%Y%m%d')

        for slug in slugs:
            fixtures = []
            try:
                fixtures += client.get_schedule(team_id, season=season, league_slug=slug)
            except EspnError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik jadwal {slug}: {exc}'))

            try:
                # get_schedule (per tim) kadang kelewat match kecil (mis.
                # friendly pramusim) — scoreboard (per tanggal) nangkep itu,
                # termasuk match yang LAGI JALAN sekarang.
                today_scoreboard = client.get_scoreboard(today, league_slug=slug)
                fixtures += [
                    e for e in today_scoreboard if self._involves_team(e, team_id)
                ]
            except EspnError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik scoreboard {slug}: {exc}'))

            self.stdout.write(f'{slug}: {len(fixtures)} fixture')

            for event_data in fixtures:
                if event_data['id'] in seen_ids:
                    continue
                seen_ids.add(event_data['id'])
                fixtures_total += 1

                try:
                    match, _ = self._save_match(event_data, mu_team_id=team_id, league_slug=slug)
                except EspnError as exc:
                    self.stdout.write(self.style.WARNING(f'  gagal proses match: {exc}'))
                    continue

                comp = event_data['competitions'][0]
                state = (comp.get('status') or {}).get('type', {}).get('state')
                if state not in ('in', 'post'):
                    continue

                try:
                    summary = client.get_summary(event_data['id'], league_slug=slug)
                except EspnError as exc:
                    self.stdout.write(
                        self.style.WARNING(f'  gagal narik summary match {match.id}: {exc}')
                    )
                    continue

                store_raw(DataSource.ESPN, 'summary', event_data['id'], summary)

                commentary = summary.get('commentary') or []
                events_total += self._save_events(
                    match, summary.get('keyEvents') or [], commentary
                )
                plays_total += self._save_plays(match, commentary)
                self._save_statistics(match, summary.get('boxscore') or {})
                players_total += self._save_rosters(match, summary.get('rosters') or [])

                # Tanpa catatan ini, kartu Kesehatan Sumber bakal terus bilang
                # ESPN "berhenti" padahal dia justru yang paling sering jalan.
                MatchIngest.objects.update_or_create(
                    match=match,
                    source=DataSource.ESPN,
                    defaults={'rows': events_total + plays_total + players_total},
                )
                processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {fixtures_total} fixture unik dari {len(slugs)} kompetisi, '
                f'{processed} match selesai diproses, {events_total} event, '
                f'{plays_total} play, {players_total} statistik pemain disimpan.'
            )
        )

    def _save_match(self, event_data, mu_team_id, league_slug=''):
        comp = event_data['competitions'][0]
        home = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
        away = next(c for c in comp['competitors'] if c['homeAway'] == 'away')

        home_team = self._upsert_team(home['team'], mu_team_id)
        away_team = self._upsert_team(away['team'], mu_team_id)

        kickoff_at = self._parse_kickoff(event_data['date'])
        status_type = (comp.get('status') or {}).get('type', {})
        venue = (comp.get('venue') or {}).get('fullName', '') or ''
        season_info = event_data.get('season') or {}

        return resolve_match(
            source=DataSource.ESPN,
            external_id=int(event_data['id']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_name': season_info.get('displayName', '')
                or SLUG_LABELS.get(league_slug, league_slug),
                'season': season_info.get('year'),
                'round': '',
                'venue': venue,
                'status': _map_status(status_type),
                'home_score': self._parse_score(home),
                'away_score': self._parse_score(away),
            },
        )

    @staticmethod
    def _involves_team(event_data, team_id):
        comp = event_data.get('competitions', [{}])[0]
        return any(str(c.get('id')) == str(team_id) for c in comp.get('competitors', []))

    def _upsert_team(self, team_data, mu_team_id):
        logos = team_data.get('logos') or []
        logo_url = logos[0]['href'] if logos else ''
        team, _ = resolve_team(
            source=DataSource.ESPN,
            external_id=int(team_data['id']),
            defaults={
                'name': team_data.get('displayName', ''),
                'logo_url': logo_url,
                'is_manchester_united': str(team_data['id']) == str(mu_team_id),
            },
        )
        return team

    @staticmethod
    def _parse_score(competitor):
        score = competitor.get('score')
        # Endpoint schedule/summary kasih {'value': N, ...}, scoreboard kasih
        # string/number langsung ("0") — dua-duanya perlu ditangani.
        if isinstance(score, dict):
            score = score.get('value')
        try:
            return int(score)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_kickoff(value):
        naive = datetime.strptime(value, '%Y-%m-%dT%H:%MZ')
        return timezone.make_aware(naive, dt_timezone.utc)

    def _save_events(self, match, key_events, commentary):
        MatchEvent.objects.filter(match=match).delete()
        seen = set()
        count = 0

        for event in key_events:
            type_slug = (event.get('type') or {}).get('type', '')
            event_type = self._map_event_type(type_slug)
            if event_type is None:
                continue

            team_data = event.get('team')
            if not team_data:
                continue

            team, _ = resolve_team(
                source=DataSource.ESPN,
                external_id=int(team_data['id']),
                defaults={'name': team_data.get('displayName', '')},
            )

            participants = event.get('participants') or []
            player = self._resolve_participant(participants, 0, team)
            assist_player = self._resolve_participant(participants, 1, team)

            minute, extra_minute = self._parse_clock((event.get('clock') or {}).get('displayValue'))

            # Nama pemain ikut jadi kunci: dalam 1 menit yang sama bisa ada
            # beberapa substitusi buat tim yang sama (mis. 3 pemain sekaligus
            # di menit 61), dan itu harus tetep kecatat semua.
            dedup_key = (event_type, minute, team.id, player.id if player else None)
            seen.add(dedup_key)

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player,
                assist_player=assist_player,
                event_type=event_type,
                detail=(event.get('type') or {}).get('text', '') or '',
                minute=minute,
                extra_minute=extra_minute,
            )
            count += 1

        # Fallback: match kecil sering nggak dapet keyEvents terstruktur, tapi
        # commentary-nya tetep ada — dan tiap entri punya `play.type.type`
        # (slug mesin) plus `play.participants`, jadi nggak perlu nebak-nebak
        # dari kalimatnya. Skip yang udah ke-cover keyEvents di atas.
        for entry in commentary:
            play = entry.get('play') or {}
            event_type = self._map_event_type((play.get('type') or {}).get('type', ''))
            if event_type is None:
                continue

            team = self._team_by_name(match, (play.get('team') or {}).get('displayName'))
            if team is None:
                continue

            minute, extra_minute = self._parse_clock((play.get('clock') or {}).get('displayValue'))
            participants = play.get('participants') or []
            player = self._resolve_commentary_player(self._participant_name(participants, 0), team)
            assist_player = self._resolve_commentary_player(
                self._participant_name(participants, 1), team
            )

            dedup_key = (event_type, minute, team.id, player.id if player else None)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player,
                assist_player=assist_player,
                event_type=event_type,
                # Label pendek ('Goal - Header'), bukan kalimat commentary utuh.
                detail=(play.get('type') or {}).get('text', '')[:150],
                minute=minute,
                extra_minute=extra_minute,
            )
            count += 1

        return count

    def _save_plays(self, match, commentary):
        """Simpen SELURUH play-by-play, bukan cuma yang layak masuk timeline.
        Ini bahan mentah buat ngitung momentum serangan."""
        MatchPlay.objects.filter(match=match).delete()

        rows = {}
        for entry in commentary:
            play = entry.get('play') or {}
            play_type = (play.get('type') or {}).get('type', '')
            play_id = play.get('id')
            # ESPN ngulang play yang sama di beberapa entri commentary dengan
            # sequence beda — tanpa dedup per play.id, pelanggaran kehitung
            # dobel dan momentumnya jadi ngaco.
            if not play_type or not play_id or play_id in rows:
                continue

            team = self._team_by_name(match, (play.get('team') or {}).get('displayName'))
            minute, extra_minute = self._parse_clock((play.get('clock') or {}).get('displayValue'))
            participants = play.get('participants') or []
            player = self._resolve_commentary_player(
                self._participant_name(participants, 0), team
            )

            rows[play_id] = MatchPlay(
                match=match,
                team=team,
                player=player,
                external_id=str(play_id),
                play_type=play_type,
                text=play.get('text') or entry.get('text') or '',
                minute=minute,
                extra_minute=extra_minute,
                period=(play.get('period') or {}).get('number'),
                sequence=entry.get('sequence'),
                # ESPN ngirim 0.0/0.0 buat kejadian yang nggak punya titik
                # di lapangan (kartu, substitusi) — itu bukan pojok lapangan,
                # itu "nggak ada data". Disimpen null biar nggak dihitung
                # sebagai posisi beneran pas ngitung momentum.
                field_x=self._nullable_position(play.get('fieldPositionX')),
                field_y=self._nullable_position(play.get('fieldPositionY')),
            )

        self._normalize_positions(rows.values())
        MatchPlay.objects.bulk_create(rows.values())
        return len(rows)

    @staticmethod
    def _normalize_positions(plays):
        """Samakan koordinat ESPN ke satu konvensi: 0..1, dan 0 = di gawang lawan.

        ESPN mengirim DUA format berbeda, dan bedanya bukan cuma skala:

        | | gol | tembakan tepat | pelanggaran |
        |---|---|---|---|
        | format lama (0..1)   | 0.225 | 0.290 | 0.632 |
        | format baru (0..100) | 91.5  | 83.4  | 51.3  |

        Di format lama 0 berarti di garis gawang yang diserang; di format baru
        justru 100 yang berarti di gawang. Jadi arahnya TERBALIK, bukan sekadar
        dikali seratus. Membagi 100 saja akan membuat gol dibaca sebagai
        kejadian paling tidak berbahaya di lapangan.

        Format baru muncul di laga musim 2026 (Juli 2026 ke atas), lama di
        seluruh laga sebelumnya. Deteksinya per laga, bukan per nilai: nilai
        0..100 yang kebetulan jatuh di bawah 1 tidak bisa dibedakan sendirian,
        tapi satu laga tidak pernah mencampur dua format (dicek ke 419 laga di
        produksi: nol yang campur).

        Kenapa ini berbahaya kalau lolos: `_danger` di momentum.py menjepit
        hasilnya ke [0,1], jadi nilai 0..100 tidak pernah error — play biasa
        cuma diam-diam jadi bahaya minimum dan pelanggaran jadi maksimum, dan
        kurvanya salah tanpa satu pun gejala.
        """
        nilai = [
            v for p in plays for v in (p.field_x, p.field_y) if v is not None
        ]
        if not nilai or max(nilai) <= 1:
            return  # format lama, sudah sesuai konvensi

        for p in plays:
            if p.field_x is not None:
                # Dibalik: format baru menaruh gawang yang diserang di 100.
                p.field_x = 1.0 - (p.field_x / 100.0)
            if p.field_y is not None:
                # Cuma diskalakan. Arah sumbu Y belum terbukti ikut terbalik,
                # dan tidak ada satu pun konsumen field_y hari ini — menebak
                # arahnya lebih buruk daripada mencatat bahwa itu belum diuji.
                p.field_y = p.field_y / 100.0

    @staticmethod
    def _nullable_position(value):
        if value in (None, 0, 0.0):
            return None
        return value

    @staticmethod
    def _participant_name(participants, index):
        if index >= len(participants):
            return None
        return ((participants[index] or {}).get('athlete') or {}).get('displayName')

    @staticmethod
    def _team_by_name(match, name):
        """Cocokin nama tim dari commentary ke home/away match ini.

        Commentary nulis nama agak beda dari nama resmi ('Brighton and Hove
        Albion' vs 'Brighton & Hove Albion'), jadi pakai matcher yang sama
        dengan sistem dedup. Return None kalau nggak yakin — jangan nebak
        home_team, karena itu bikin event tim tamu salah atribusi.
        """
        if not name:
            return None
        for team in (match.home_team, match.away_team):
            if team_names_match(team.name, name):
                return team
        return None

    @staticmethod
    def _resolve_commentary_player(name, team):
        if not name or not team:
            return None
        player, _ = resolve_player(
            source=DataSource.ESPN_COMMENTARY,
            external_id=_stable_id(name),
            team=team,
            defaults={'name': name, 'team': team},
        )
        return player

    def _resolve_participant(self, participants, index, team):
        if index >= len(participants):
            return None
        athlete = participants[index].get('athlete') or {}
        if not athlete.get('id'):
            return None
        player, _ = resolve_player(
            source=DataSource.ESPN,
            external_id=int(athlete['id']),
            team=team,
            defaults={'name': athlete.get('displayName', ''), 'team': team},
        )
        return player

    @staticmethod
    def _map_event_type(type_slug):
        type_slug = type_slug or ''
        if 'goal' in type_slug:
            return MatchEvent.EventType.GOAL
        if 'card' in type_slug:
            return MatchEvent.EventType.CARD
        if 'substitution' in type_slug:
            return MatchEvent.EventType.SUBSTITUTION
        if 'var' in type_slug:
            return MatchEvent.EventType.VAR
        return None

    @staticmethod
    def _parse_clock(display_value):
        if not display_value:
            return 0, None
        value = display_value.replace("'", '')
        if '+' in value:
            minute, extra = value.split('+', 1)
            try:
                return int(minute), int(extra)
            except ValueError:
                return 0, None
        try:
            return int(value), None
        except ValueError:
            return 0, None

    def _save_statistics(self, match, boxscore):
        for team_stats in boxscore.get('teams') or []:
            team_data = team_stats.get('team') or {}
            if not team_data.get('id'):
                continue

            team, _ = resolve_team(
                source=DataSource.ESPN,
                external_id=int(team_data['id']),
                defaults={'name': team_data.get('displayName', '')},
            )

            stats = {
                s.get('name'): s.get('displayValue') for s in team_stats.get('statistics') or []
            }

            values = {
                'possession_pct': self._parse_stat_int(stats.get('possessionPct')),
                'shots_total': self._parse_stat_int(stats.get('totalShots')),
                'shots_on_target': self._parse_stat_int(stats.get('shotsOnTarget')),
                'corners': self._parse_stat_int(stats.get('wonCorners')),
                'fouls': self._parse_stat_int(stats.get('foulsCommitted')),
                'offsides': self._parse_stat_int(stats.get('offsides')),
                'yellow_cards': self._parse_stat_int(stats.get('yellowCards')),
                'red_cards': self._parse_stat_int(stats.get('redCards')),
                'passes_total': self._parse_stat_int(stats.get('totalPasses')),
                'passes_accurate': self._parse_stat_int(stats.get('accuratePasses')),
                'saves': self._parse_stat_int(stats.get('saves')),
                'shots_blocked': self._parse_stat_int(stats.get('blockedShots')),
                'crosses_total': self._parse_stat_int(stats.get('totalCrosses')),
                'crosses_accurate': self._parse_stat_int(stats.get('accurateCrosses')),
                'long_balls_total': self._parse_stat_int(stats.get('totalLongBalls')),
                'long_balls_accurate': self._parse_stat_int(stats.get('accurateLongBalls')),
                'tackles_total': self._parse_stat_int(stats.get('totalTackles')),
                'tackles_won': self._parse_stat_int(stats.get('effectiveTackles')),
                'interceptions': self._parse_stat_int(stats.get('interceptions')),
                'clearances_total': self._parse_stat_int(stats.get('totalClearance')),
                'clearances_effective': self._parse_stat_int(stats.get('effectiveClearance')),
                'penalty_goals': self._parse_stat_int(stats.get('penaltyKickGoals')),
                'penalty_shots': self._parse_stat_int(stats.get('penaltyKickShots')),
            }

            values = self._buang_nol_palsu(values)

            row, _ = MatchTeamStatistics.objects.get_or_create(match=match, team=team)
            updates, sources = resolve_updates(row.field_sources, DataSource.ESPN, values)
            if updates:
                updates['field_sources'] = sources
                MatchTeamStatistics.objects.filter(pk=row.pk).update(**updates)

    @staticmethod
    def _buang_nol_palsu(values):
        """Ubah blok statistik kosong jadi None, bukan nol.

        Untuk sebagian laga ESPN mengirim struktur `statistics` yang lengkap
        tapi semua isinya '0'. Itu artinya "kami tidak punya datanya", bukan
        "timnya benar-benar mencatat nol". Karena nilainya non-null, angka itu
        lolos semua penyaring dan ikut masuk rata-rata.

        Akibatnya di produksi: rata-rata penguasaan bola MU musim 2022 terbaca
        **49,4%** padahal sebenarnya **56,4%** — selisih 7 poin dari 8 laga,
        cukup untuk mengarang cerita "MU ambruk lalu bangkit" yang seluruhnya
        artefak data.

        Deteksinya penguasaan bola DAN total umpan yang dua-duanya nol. Tim
        yang benar-benar bermain bisa saja nol tembakan — itu jarang tapi sah —
        tapi tidak mungkin nol penguasaan bola sekaligus nol umpan.
        """
        if values.get('possession_pct') in (0, None) and values.get('passes_total') in (0, None):
            return {k: None for k in values}
        return values

    # Nama stat ESPN -> nama field PlayerMatchStatistics.
    _PLAYER_STAT_FIELDS = {
        'totalGoals': 'goals',
        'goalAssists': 'assists',
        'totalShots': 'shots_total',
        'shotsOnTarget': 'shots_on_target',
        'ownGoals': 'own_goals',
        'foulsCommitted': 'fouls_committed',
        'foulsSuffered': 'fouls_suffered',
        'offsides': 'offsides',
        'yellowCards': 'yellow_cards',
        'redCards': 'red_cards',
        'saves': 'saves',
        'shotsFaced': 'shots_faced',
        'goalsConceded': 'goals_conceded',
    }

    def _save_rosters(self, match, rosters):
        """Simpen formasi awal + statistik tiap pemain di match ini."""
        saved = 0
        for roster in rosters or []:
            team_data = roster.get('team') or {}
            if not team_data.get('id'):
                continue

            team, _ = resolve_team(
                source=DataSource.ESPN,
                external_id=int(team_data['id']),
                defaults={'name': team_data.get('displayName', '')},
            )

            formation = roster.get('formation') or ''
            if formation:
                field = (
                    'home_formation' if team.id == match.home_team_id else 'away_formation'
                )
                Match.objects.filter(pk=match.pk).update(**{field: formation[:20]})

            for entry in roster.get('roster') or []:
                athlete = entry.get('athlete') or {}
                if not athlete.get('id'):
                    continue

                player, _ = resolve_player(
                    source=DataSource.ESPN,
                    external_id=int(athlete['id']),
                    team=team,
                    defaults={'name': athlete.get('displayName', ''), 'team': team},
                )

                stats = {s.get('name'): s.get('displayValue') for s in entry.get('stats') or []}
                defaults = {
                    field: self._parse_stat_int(stats.get(espn_name))
                    for espn_name, field in self._PLAYER_STAT_FIELDS.items()
                }
                defaults.update(
                    {
                        'team': team,
                        'starter': bool(entry.get('starter')),
                        # formationPlace '0' artinya cadangan, bukan posisi 0.
                        'formation_place': self._parse_stat_int(entry.get('formationPlace')) or None,
                        'shirt_number': self._parse_stat_int(entry.get('jersey')),
                        'subbed_in': bool(entry.get('subbedIn')),
                        'subbed_out': bool(entry.get('subbedOut')),
                    }
                )

                row, _ = PlayerMatchStatistics.objects.get_or_create(
                    match=match, player=player, defaults={'team': team}
                )
                updates, sources = resolve_updates(row.field_sources, DataSource.ESPN, defaults)
                if updates:
                    updates['field_sources'] = sources
                    PlayerMatchStatistics.objects.filter(pk=row.pk).update(**updates)
                saved += 1

        return saved

    @staticmethod
    def _parse_stat_int(value):
        if value in (None, ''):
            return None
        cleaned = re.sub(r'[^0-9.\-]', '', str(value))
        if not cleaned:
            return None
        try:
            return int(round(float(cleaned)))
        except ValueError:
            return None
