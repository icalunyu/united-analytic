from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from matches.dedup import resolve_match
from matches.models import Match
from matches.services import APIFootballClient, APIFootballError
from players.dedup import resolve_team
from players.models import DataSource

# API-Football pakai banyak short status code; kita sederhanakan ke Match.Status.
STATUS_MAP = {
    'TBD': Match.Status.NOT_STARTED,
    'NS': Match.Status.NOT_STARTED,
    '1H': Match.Status.LIVE,
    '2H': Match.Status.LIVE,
    'ET': Match.Status.LIVE,
    'BT': Match.Status.LIVE,
    'P': Match.Status.LIVE,
    'SUSP': Match.Status.LIVE,
    'INT': Match.Status.LIVE,
    'LIVE': Match.Status.LIVE,
    'HT': Match.Status.HALFTIME,
    'FT': Match.Status.FINISHED,
    'AET': Match.Status.EXTRA_TIME,
    'PEN': Match.Status.PENALTIES,
    'PST': Match.Status.POSTPONED,
    'CANC': Match.Status.CANCELLED,
    'ABD': Match.Status.CANCELLED,
    'AWD': Match.Status.CANCELLED,
    'WO': Match.Status.CANCELLED,
}


class Command(BaseCommand):
    help = 'Narik fixtures (jadwal & hasil) dari API-Football, simpan/update ke database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--next',
            type=int,
            default=None,
            help='Jumlah fixture berikutnya yang ditarik (butuh paid plan API-Football)',
        )
        parser.add_argument(
            '--last',
            type=int,
            default=None,
            help='Jumlah fixture terakhir yang ditarik (butuh paid plan API-Football)',
        )
        parser.add_argument('--season', type=int, default=None, help='Filter musim, contoh: 2025')
        parser.add_argument(
            '--team-id', type=int, default=None, help='Override MU_TEAM_ID dari settings'
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.MU_TEAM_ID
        next_n = options['next']
        last_n = options['last']
        season = options['season']

        # Free tier API-Football tidak mendukung parameter next/last, jadi
        # default-nya narik seluruh jadwal semusim (team + season) sekali
        # request, lalu semuanya disimpan/di-update ke DB.
        if next_n is None and last_n is None and season is None:
            now = timezone.now()
            season = now.year if now.month >= 7 else now.year - 1

        try:
            client = APIFootballClient()
            fixtures = client.get_fixtures(
                team_id=team_id, season=season, next=next_n, last=last_n
            )
        except APIFootballError as exc:
            raise CommandError(str(exc)) from exc

        created_count = 0
        updated_count = 0

        for fixture in fixtures:
            match, created = self._save_fixture(fixture, mu_team_id=team_id)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(fixtures)} fixture diproses '
                f'({created_count} baru, {updated_count} update).'
            )
        )

    def _upsert_team(self, team_data, mu_team_id):
        team_id = team_data['id']
        team, _ = resolve_team(
            source=DataSource.API_FOOTBALL,
            external_id=team_id,
            defaults={
                'name': team_data.get('name', ''),
                'logo_url': team_data.get('logo', '') or '',
                'is_manchester_united': team_id == mu_team_id,
            },
        )
        return team

    def _save_fixture(self, fixture, mu_team_id):
        fixture_info = fixture['fixture']
        league_info = fixture.get('league', {})
        teams_info = fixture['teams']
        goals_info = fixture.get('goals', {})

        home_team = self._upsert_team(teams_info['home'], mu_team_id)
        away_team = self._upsert_team(teams_info['away'], mu_team_id)

        kickoff_at = parse_datetime(fixture_info['date'])
        status_short = fixture_info.get('status', {}).get('short', 'NS')
        venue = (fixture_info.get('venue') or {}).get('name') or ''

        return resolve_match(
            source=DataSource.API_FOOTBALL,
            external_id=fixture_info['id'],
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_id': league_info.get('id'),
                'league_name': league_info.get('name', ''),
                'season': league_info.get('season'),
                'round': league_info.get('round', ''),
                'venue': venue,
                'referee': fixture_info.get('referee') or '',
                'status': STATUS_MAP.get(status_short, Match.Status.NOT_STARTED),
                'home_score': goals_info.get('home'),
                'away_score': goals_info.get('away'),
            },
        )
