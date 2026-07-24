import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import Match, MatchEvent
from matches.services import HighlightlyClient, HighlightlyError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource

EVENT_TYPE_MAP = {
    'goal': MatchEvent.EventType.GOAL,
    'card': MatchEvent.EventType.CARD,
    'subst': MatchEvent.EventType.SUBSTITUTION,
    'substitution': MatchEvent.EventType.SUBSTITUTION,
    'var': MatchEvent.EventType.VAR,
}

STATUS_MAP = {
    'Not started': Match.Status.NOT_STARTED,
    'Finished': Match.Status.FINISHED,
    'Postponed': Match.Status.POSTPONED,
    'Cancelled': Match.Status.CANCELLED,
}


class Command(BaseCommand):
    help = (
        'Narik match events (gol/kartu/substitusi) MU dari Highlightly buat '
        'match yang sudah selesai, simpan/update ke database.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=int, default=None, help='Override HIGHLIGHTLY_MU_TEAM_ID dari settings'
        )
        parser.add_argument('--season', type=int, default=None, help='Contoh: 2025')

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.HIGHLIGHTLY_MU_TEAM_ID
        if not team_id:
            raise CommandError(
                'HIGHLIGHTLY_MU_TEAM_ID belum di-set di .env, atau override lewat --team-id.'
            )
        team_id = int(team_id)

        try:
            client = HighlightlyClient()
            matches = client.get_matches(team_id=team_id, season=options['season'], limit=100)
        except HighlightlyError as exc:
            raise CommandError(str(exc)) from exc

        processed = 0
        events_total = 0

        for match_data in matches:
            match, _ = self._save_match(match_data, mu_team_id=team_id)
            state = match_data.get('state', {})
            if state.get('description') != 'Finished':
                continue

            try:
                events = client.get_match_events(match_data['id'])
            except HighlightlyError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik event match {match.id}: {exc}'))
                continue
            finally:
                time.sleep(0.5)

            events_total += self._save_events(match, events)
            processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {processed} match selesai diproses, {events_total} event disimpan.'
            )
        )

    def _save_match(self, match_data, mu_team_id):
        home_team = self._upsert_team(match_data['homeTeam'], mu_team_id)
        away_team = self._upsert_team(match_data['awayTeam'], mu_team_id)

        kickoff_at = datetime.fromisoformat(match_data['date'].replace('Z', '+00:00'))
        if timezone.is_naive(kickoff_at):
            kickoff_at = timezone.make_aware(kickoff_at)

        state = match_data.get('state', {})
        home_score, away_score = self._parse_score(state.get('score', {}).get('current'))
        league = match_data.get('league', {})

        return resolve_match(
            source=DataSource.HIGHLIGHTLY,
            external_id=match_data['id'],
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_id': league.get('id'),
                'league_name': league.get('name', ''),
                'season': league.get('season'),
                'round': match_data.get('round', '') or '',
                'venue': '',
                'referee': '',
                'status': STATUS_MAP.get(state.get('description'), Match.Status.NOT_STARTED),
                'home_score': home_score,
                'away_score': away_score,
            },
        )

    def _upsert_team(self, team_data, mu_team_id):
        team, _ = resolve_team(
            source=DataSource.HIGHLIGHTLY,
            external_id=team_data['id'],
            defaults={
                'name': team_data.get('name', ''),
                'logo_url': team_data.get('logo', '') or '',
                'is_manchester_united': team_data['id'] == mu_team_id,
            },
        )
        return team

    @staticmethod
    def _parse_score(score):
        if not score or '-' not in score:
            return None, None
        home, _, away = score.partition('-')
        try:
            return int(home.strip()), int(away.strip())
        except ValueError:
            return None, None

    def _save_events(self, match, events):
        items = events.get('data', events) if isinstance(events, dict) else events
        MatchEvent.objects.filter(match=match).delete()

        count = 0
        for event in items:
            event_type = EVENT_TYPE_MAP.get((event.get('type') or '').lower())
            if event_type is None:
                continue

            team_data = event.get('team') or {}
            if not team_data.get('id'):
                continue

            team, _ = resolve_team(
                source=DataSource.HIGHLIGHTLY,
                external_id=team_data['id'],
                defaults={
                    'name': team_data.get('name', ''),
                    'logo_url': team_data.get('logo', '') or '',
                },
            )

            player = None
            if event.get('playerId'):
                player, _ = resolve_player(
                    source=DataSource.HIGHLIGHTLY,
                    external_id=event['playerId'],
                    team=team,
                    defaults={'name': event.get('player', ''), 'team': team},
                )

            assist_player = None
            if event.get('assistingPlayerId'):
                assist_player, _ = resolve_player(
                    source=DataSource.HIGHLIGHTLY,
                    external_id=event['assistingPlayerId'],
                    team=team,
                    defaults={'name': event.get('assist', ''), 'team': team},
                )

            minute, extra_minute = self._parse_time(event.get('time'))

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player,
                assist_player=assist_player,
                event_type=event_type,
                detail=event.get('type', '') or '',
                minute=minute,
                extra_minute=extra_minute,
            )
            count += 1
        return count

    @staticmethod
    def _parse_time(value):
        value = str(value or '0')
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
