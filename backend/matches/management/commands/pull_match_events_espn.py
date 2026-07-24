import re
import zlib
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import Match, MatchEvent, MatchTeamStatistics
from matches.services import EspnClient, EspnError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource

# Match kecil (mis. friendly pramusim) sering nggak dapet `keyEvents`
# terstruktur dari ESPN, cuma `commentary` teks bebas. Pola ini nge-parse
# format standar komentator ESPN buat gol/kartu/substitusi.
COMMENTARY_GOAL_RE = re.compile(r'^Goal!.*?\.\s*([^(]+?)\s*\(([^)]+)\)')
COMMENTARY_CARD_RE = re.compile(
    r'^([^(]+?)\s*\(([^)]+)\)\s+is shown the (?:second )?(?:yellow|red) card', re.IGNORECASE
)
COMMENTARY_SUB_RE = re.compile(r'^Substitution,\s*([^.]+)\.\s*([^(]+?)\s+replaces\s+([^.]+)\.')
COMMENTARY_ASSIST_RE = re.compile(r'[Aa]ssisted by ([^.,]+)')


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

                events_total += self._save_events(
                    match, summary.get('keyEvents') or [], summary.get('commentary') or []
                )
                self._save_statistics(match, summary.get('boxscore') or {})
                processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {fixtures_total} fixture unik dari {len(slugs)} kompetisi, '
                f'{processed} match selesai diproses, {events_total} event disimpan.'
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

            dedup_key = (event_type, minute, team.id)
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

        # Fallback: match kecil sering nggak dapet keyEvents terstruktur,
        # cuma commentary teks. Skip kalau minute+tipe+tim udah ke-cover
        # dari keyEvents di atas.
        for entry in commentary:
            minute = self._commentary_minute(entry)
            if minute is None:
                continue

            parsed = self._parse_commentary_text(entry.get('text', ''), match)
            if parsed is None:
                continue
            event_type, team, player, assist_player = parsed

            dedup_key = (event_type, minute, team.id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player,
                assist_player=assist_player,
                event_type=event_type,
                detail=entry.get('text', '')[:150],
                minute=minute,
            )
            count += 1

        return count

    @staticmethod
    def _commentary_minute(entry):
        display = (entry.get('time') or {}).get('displayValue')
        if not display:
            return None
        try:
            return int(display.replace("'", '').split('+')[0])
        except ValueError:
            return None

    def _parse_commentary_text(self, text, match):
        m = COMMENTARY_GOAL_RE.match(text)
        if m:
            player_name, team_name = m.group(1).strip(), m.group(2).strip()
            team = self._team_by_name(match, team_name)
            player = self._resolve_commentary_player(player_name, team)
            assist_match = COMMENTARY_ASSIST_RE.search(text)
            assist_player = (
                self._resolve_commentary_player(assist_match.group(1).strip(), team)
                if assist_match
                else None
            )
            return MatchEvent.EventType.GOAL, team, player, assist_player

        m = COMMENTARY_CARD_RE.match(text)
        if m:
            player_name, team_name = m.group(1).strip(), m.group(2).strip()
            team = self._team_by_name(match, team_name)
            player = self._resolve_commentary_player(player_name, team)
            return MatchEvent.EventType.CARD, team, player, None

        m = COMMENTARY_SUB_RE.match(text)
        if m:
            team_name, player_in, player_out = (
                m.group(1).strip(),
                m.group(2).strip(),
                m.group(3).strip(),
            )
            team = self._team_by_name(match, team_name)
            player = self._resolve_commentary_player(player_in, team)
            assist_player = self._resolve_commentary_player(player_out, team)
            return MatchEvent.EventType.SUBSTITUTION, team, player, assist_player

        return None

    @staticmethod
    def _team_by_name(match, name):
        name = name.strip().lower()
        if match.away_team.name.strip().lower() == name:
            return match.away_team
        return match.home_team

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

            MatchTeamStatistics.objects.update_or_create(
                match=match,
                team=team,
                defaults={
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
                },
            )

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
