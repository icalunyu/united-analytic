from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from matches.dedup import resolve_match
from matches.models import Match
from matches.services import FootballDataClient, FootballDataError
from players.dedup import resolve_team
from players.models import DataSource

# football-data.org pakai status yang berbeda dari API-Football; kita
# sederhanakan ke Match.Status yang sama supaya kedua sumber konsisten.
STATUS_MAP = {
    'SCHEDULED': Match.Status.NOT_STARTED,
    'TIMED': Match.Status.NOT_STARTED,
    'IN_PLAY': Match.Status.LIVE,
    'PAUSED': Match.Status.HALFTIME,
    'FINISHED': Match.Status.FINISHED,
    'SUSPENDED': Match.Status.LIVE,
    'POSTPONED': Match.Status.POSTPONED,
    'CANCELLED': Match.Status.CANCELLED,
    'AWARDED': Match.Status.CANCELLED,
}


class Command(BaseCommand):
    help = 'Narik fixtures MU dari football-data.org, simpan/update ke database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=int, default=None, help='Override FOOTBALL_DATA_MU_TEAM_ID dari settings'
        )
        parser.add_argument('--date-from', type=str, default=None, help='Format YYYY-MM-DD')
        parser.add_argument('--date-to', type=str, default=None, help='Format YYYY-MM-DD')
        parser.add_argument('--season', type=int, default=None, help='Contoh: 2025')
        parser.add_argument(
            '--status', type=str, default=None, help='SCHEDULED, FINISHED, IN_PLAY, dll'
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.FOOTBALL_DATA_MU_TEAM_ID

        try:
            client = FootballDataClient()
            matches = client.get_team_matches(
                team_id=team_id,
                date_from=options['date_from'],
                date_to=options['date_to'],
                season=options['season'],
                status=options['status'],
            )
        except FootballDataError as exc:
            raise CommandError(str(exc)) from exc

        created_count = 0
        updated_count = 0

        for match_data in matches:
            _, created = self._save_match(match_data, mu_team_id=team_id)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(matches)} match diproses '
                f'({created_count} baru, {updated_count} update).'
            )
        )

    def _upsert_team(self, team_data, mu_team_id):
        team_id = team_data['id']
        team, _ = resolve_team(
            source=DataSource.FOOTBALL_DATA,
            external_id=team_id,
            defaults={
                'name': team_data.get('name', ''),
                'short_name': team_data.get('shortName', '') or '',
                'logo_url': team_data.get('crest', '') or '',
                'is_manchester_united': team_id == mu_team_id,
            },
        )
        return team

    def _save_match(self, match_data, mu_team_id):
        home_team = self._upsert_team(match_data['homeTeam'], mu_team_id)
        away_team = self._upsert_team(match_data['awayTeam'], mu_team_id)

        competition = match_data.get('competition', {})
        full_time_score = (match_data.get('score') or {}).get('fullTime', {})
        referees = match_data.get('referees') or []

        kickoff_at = parse_datetime(match_data['utcDate'])
        season = kickoff_at.year if kickoff_at.month >= 7 else kickoff_at.year - 1
        round_label = (
            f"Matchday {match_data['matchday']}" if match_data.get('matchday') else ''
        )

        return resolve_match(
            source=DataSource.FOOTBALL_DATA,
            external_id=match_data['id'],
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_id': competition.get('id'),
                'league_name': competition.get('name', ''),
                'season': season,
                'round': round_label,
                'venue': match_data.get('venue') or '',
                'referee': referees[0]['name'] if referees else '',
                'status': STATUS_MAP.get(match_data.get('status'), Match.Status.NOT_STARTED),
                'home_score': full_time_score.get('home'),
                'away_score': full_time_score.get('away'),
            },
        )
