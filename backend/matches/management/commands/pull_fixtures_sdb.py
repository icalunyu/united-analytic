from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import Match
from matches.services import TheSportsDbClient, TheSportsDbError
from players.dedup import resolve_team
from players.models import DataSource

STATUS_MAP = {
    'NS': Match.Status.NOT_STARTED,
    'FT': Match.Status.FINISHED,
    'AET': Match.Status.EXTRA_TIME,
    'PEN': Match.Status.PENALTIES,
    'HT': Match.Status.HALFTIME,
    '1H': Match.Status.LIVE,
    '2H': Match.Status.LIVE,
    'POSTPONED': Match.Status.POSTPONED,
    'CANCELLED': Match.Status.CANCELLED,
    'CANC': Match.Status.CANCELLED,
}


class Command(BaseCommand):
    help = (
        'Narik fixtures MU dari TheSportsDB (fallback kalau API-Football/'
        'football-data.org kena quota), simpan/update ke database. Tim yang '
        'punya idAPIfootball di-link langsung ke data API-Football, bukan '
        'cocokin nama.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=str, default=None, help='Override THESPORTSDB_MU_TEAM_ID dari settings'
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.THESPORTSDB_MU_TEAM_ID
        client = TheSportsDbClient()
        self._team_cache = {}

        try:
            events = client.get_next_events(team_id) + client.get_last_events(team_id)
        except TheSportsDbError as exc:
            raise CommandError(str(exc)) from exc

        created_count = 0
        updated_count = 0

        for event in events:
            try:
                _, created = self._save_event(client, event, mu_team_id=team_id)
            except TheSportsDbError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal proses event {event.get("idEvent")}: {exc}'))
                continue

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(events)} event diproses '
                f'({created_count} baru, {updated_count} update).'
            )
        )

    def _upsert_team(self, client, team_id, team_name, mu_team_id):
        if team_id in self._team_cache:
            return self._team_cache[team_id]

        detail = client.get_team(team_id)
        api_football_id = (detail or {}).get('idAPIfootball')
        logo = (detail or {}).get('strBadge', '') or (detail or {}).get('strTeamBadge', '')

        cross_ref = None
        if api_football_id and str(api_football_id).isdigit():
            cross_ref = (DataSource.API_FOOTBALL, int(api_football_id))

        team, _ = resolve_team(
            source=DataSource.THESPORTSDB,
            external_id=int(team_id),
            defaults={
                'name': team_name,
                'logo_url': logo or '',
                'is_manchester_united': str(team_id) == str(mu_team_id),
            },
            cross_ref=cross_ref,
        )
        self._team_cache[team_id] = team
        return team

    def _save_event(self, client, event, mu_team_id):
        home_team = self._upsert_team(client, event['idHomeTeam'], event.get('strHomeTeam', ''), mu_team_id)
        away_team = self._upsert_team(client, event['idAwayTeam'], event.get('strAwayTeam', ''), mu_team_id)

        kickoff_at = self._parse_kickoff(event)
        season = self._parse_season(event.get('strSeason'))

        return resolve_match(
            source=DataSource.THESPORTSDB,
            external_id=int(event['idEvent']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_name': event.get('strLeague', '') or '',
                'season': season,
                'round': event.get('intRound', '') or '',
                'venue': event.get('strVenue', '') or '',
                'status': STATUS_MAP.get((event.get('strStatus') or 'NS').upper(), Match.Status.NOT_STARTED),
                'home_score': self._parse_int(event.get('intHomeScore')),
                'away_score': self._parse_int(event.get('intAwayScore')),
            },
        )

    @staticmethod
    def _parse_kickoff(event):
        date_str = event.get('dateEvent')
        time_str = event.get('strTime') or '00:00:00'
        try:
            naive = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            naive = datetime.strptime(date_str, '%Y-%m-%d')
        return timezone.make_aware(naive, dt_timezone.utc)

    @staticmethod
    def _parse_season(value):
        if not value:
            return None
        try:
            return int(str(value).split('-')[0])
        except ValueError:
            return None

    @staticmethod
    def _parse_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
