from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import Match, MatchEvent
from matches.services import EspnClient, EspnError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource

STATUS_MAP = {
    'STATUS_SCHEDULED': Match.Status.NOT_STARTED,
    'STATUS_FULL_TIME': Match.Status.FINISHED,
    'STATUS_FINAL': Match.Status.FINISHED,
    'STATUS_HALFTIME': Match.Status.HALFTIME,
    'STATUS_IN_PROGRESS': Match.Status.LIVE,
    'STATUS_POSTPONED': Match.Status.POSTPONED,
    'STATUS_CANCELED': Match.Status.CANCELLED,
    'STATUS_ABANDONED': Match.Status.CANCELLED,
}


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

        for slug in slugs:
            try:
                fixtures = client.get_schedule(team_id, season=season, league_slug=slug)
            except EspnError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik jadwal {slug}: {exc}'))
                continue

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
                if state != 'post':
                    continue

                try:
                    summary = client.get_summary(event_data['id'], league_slug=slug)
                except EspnError as exc:
                    self.stdout.write(
                        self.style.WARNING(f'  gagal narik summary match {match.id}: {exc}')
                    )
                    continue

                events_total += self._save_events(match, summary.get('keyEvents') or [])
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
        status_name = (comp.get('status') or {}).get('type', {}).get('name', '')
        venue = (comp.get('venue') or {}).get('fullName', '') or ''
        season_info = event_data.get('season') or {}

        return resolve_match(
            source=DataSource.ESPN,
            external_id=int(event_data['id']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_name': season_info.get('displayName', '') or league_slug,
                'season': season_info.get('year'),
                'round': '',
                'venue': venue,
                'status': STATUS_MAP.get(status_name, Match.Status.NOT_STARTED),
                'home_score': self._parse_score(home),
                'away_score': self._parse_score(away),
            },
        )

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
        if isinstance(score, dict) and 'value' in score:
            try:
                return int(score['value'])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _parse_kickoff(value):
        naive = datetime.strptime(value, '%Y-%m-%dT%H:%MZ')
        return timezone.make_aware(naive, dt_timezone.utc)

    def _save_events(self, match, key_events):
        MatchEvent.objects.filter(match=match).delete()
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
        return count

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
