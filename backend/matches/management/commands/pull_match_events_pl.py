from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from matches.dedup import resolve_match
from matches.models import Match, MatchEvent, MatchIngest
from matches.services import PremierLeagueClient, PremierLeagueError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource, PlayerExternalRef, TeamExternalRef


class Command(BaseCommand):
    help = (
        'Narik fixtures + match events (gol/kartu/substitusi) MU dari '
        'database resmi Premier League sendiri (footballapi.pulselive.com). '
        'Cuma cover kompetisi Premier League, riwayat sejak musim 1992/93.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=str, default=None, help='Override PL_MU_TEAM_ID dari settings'
        )
        parser.add_argument(
            '--comp-id', type=str, default=None, help='Override PL_COMPETITION_ID dari settings'
        )
        parser.add_argument('--page', type=int, default=0, help='Halaman awal (0-based)')
        parser.add_argument(
            '--pages', type=int, default=1, help='Jumlah halaman berturut-turut yang ditarik'
        )
        parser.add_argument('--page-size', type=int, default=100)

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.PL_MU_TEAM_ID
        comp_id = options['comp_id'] or settings.PL_COMPETITION_ID
        client = PremierLeagueClient()
        self._client = client
        self._player_cache = {}

        processed = 0
        events_total = 0
        fixtures_total = 0

        for page in range(options['page'], options['page'] + options['pages']):
            try:
                fixtures = client.get_fixtures(
                    team_id=team_id, comp_id=comp_id, page=page, page_size=options['page_size']
                )
            except PremierLeagueError as exc:
                raise CommandError(str(exc)) from exc

            if not fixtures:
                break

            fixtures_total += len(fixtures)

            for fixture in fixtures:
                try:
                    match, _ = self._save_match(fixture, mu_team_id=team_id)
                except (PremierLeagueError, KeyError, IndexError) as exc:
                    self.stdout.write(self.style.WARNING(f'  gagal proses fixture: {exc}'))
                    continue

                if fixture.get('status') != 'C':
                    continue

                try:
                    detail = client.get_fixture_detail(int(fixture['id']))
                except PremierLeagueError as exc:
                    self.stdout.write(
                        self.style.WARNING(f'  gagal narik detail match {match.id}: {exc}')
                    )
                    continue

                saved = self._save_events(match, detail.get('events') or [])
                events_total += saved

                # Tanpa catatan ini, kartu Kesehatan Sumber bilang Premier
                # League "berhenti" SELAMANYA — padahal command ini jalan tiap
                # malam. source_health.py masukin PREMIER_LEAGUE ke daftar yang
                # dilacak dengan ambang (26, 72) jam, dan ambang itu dibaca
                # dari MatchIngest. Nol baris = umur tak hingga = alarm palsu
                # buat feed yang sebenarnya sehat.
                MatchIngest.objects.update_or_create(
                    match=match,
                    source=DataSource.PREMIER_LEAGUE,
                    defaults={'rows': saved},
                )
                processed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {fixtures_total} fixture ditarik, {processed} match selesai diproses, '
                f'{events_total} event disimpan.'
            )
        )

    def _save_match(self, fixture, mu_team_id):
        home_data, away_data = fixture['teams'][0]['team'], fixture['teams'][1]['team']
        home_team = self._upsert_team(home_data, mu_team_id)
        away_team = self._upsert_team(away_data, mu_team_id)

        kickoff_at = self._parse_kickoff(fixture['kickoff']['millis'])
        gameweek = fixture.get('gameweek') or {}
        comp_season = (gameweek.get('compSeason') or {})

        return resolve_match(
            source=DataSource.PREMIER_LEAGUE,
            external_id=int(fixture['id']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'league_name': (comp_season.get('competition') or {}).get('description', '') or '',
                'season': self._parse_season(comp_season.get('label')),
                'round': str(gameweek.get('gameweek', '') or ''),
                'venue': (fixture.get('ground') or {}).get('name', '') or '',
                'status': Match.Status.FINISHED if fixture.get('status') == 'C' else Match.Status.NOT_STARTED,
                'home_score': fixture['teams'][0].get('score'),
                'away_score': fixture['teams'][1].get('score'),
            },
        )

    def _upsert_team(self, team_data, mu_team_id):
        team, _ = resolve_team(
            source=DataSource.PREMIER_LEAGUE,
            external_id=int(team_data['id']),
            defaults={
                'name': team_data.get('name', ''),
                'short_name': team_data.get('shortName', '') or '',
                'is_manchester_united': str(team_data['id']) == str(mu_team_id),
            },
        )
        return team

    def _save_events(self, match, events):
        MatchEvent.objects.filter(match=match).delete()

        subs = {}
        goal_and_card_events = []

        for event in events:
            etype = event.get('type')
            if etype == 'S':
                entry = subs.setdefault(event.get('id'), {})
                if event.get('description') == 'ON':
                    entry['on'] = event
                elif event.get('description') == 'OFF':
                    entry['off'] = event
            elif etype in ('G', 'P', 'B'):
                goal_and_card_events.append(event)

        count = 0

        for event in goal_and_card_events:
            team = self._team_for_id(event.get('teamId'))
            if team is None:
                continue

            player = self._resolve_person(event.get('personId'), team)
            minute = self._minute_from_clock(event.get('clock'))

            if event.get('type') == 'B':
                event_type = MatchEvent.EventType.CARD
                detail = 'Red Card' if event.get('description') == 'R' else 'Yellow Card'
            else:
                event_type = MatchEvent.EventType.GOAL
                detail = 'Penalty' if event.get('type') == 'P' else 'Goal'

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player,
                assist_player=None,
                event_type=event_type,
                detail=detail,
                minute=minute,
            )
            count += 1

        for pair in subs.values():
            on_event = pair.get('on')
            off_event = pair.get('off')
            base_event = on_event or off_event
            if base_event is None:
                continue

            team = self._team_for_id(base_event.get('teamId'))
            if team is None:
                continue

            player_in = self._resolve_person(on_event.get('personId'), team) if on_event else None
            player_out = self._resolve_person(off_event.get('personId'), team) if off_event else None
            minute = self._minute_from_clock(base_event.get('clock'))

            MatchEvent.objects.create(
                match=match,
                team=team,
                player=player_in,
                assist_player=player_out,
                event_type=MatchEvent.EventType.SUBSTITUTION,
                detail='Substitution',
                minute=minute,
            )
            count += 1

        return count

    def _team_for_id(self, team_id):
        if team_id is None:
            return None
        ref = TeamExternalRef.objects.filter(
            source=DataSource.PREMIER_LEAGUE, external_id=int(team_id)
        ).first()
        return ref.team if ref else None

    def _resolve_person(self, person_id, team):
        if person_id is None:
            return None
        person_id = int(person_id)

        if person_id in self._player_cache:
            return self._player_cache[person_id]

        ref = PlayerExternalRef.objects.filter(
            source=DataSource.PREMIER_LEAGUE, external_id=person_id
        ).first()
        if ref:
            self._player_cache[person_id] = ref.player
            return ref.player

        try:
            detail = self._client.get_player(person_id)
        except PremierLeagueError:
            return None

        name = (detail.get('name') or {}).get('display', '') or ''
        if not name:
            return None

        player, _ = resolve_player(
            source=DataSource.PREMIER_LEAGUE,
            external_id=person_id,
            team=team,
            defaults={'name': name, 'team': team},
        )
        self._player_cache[person_id] = player
        return player

    @staticmethod
    def _parse_kickoff(millis):
        return datetime.fromtimestamp(millis / 1000, tz=dt_timezone.utc)

    @staticmethod
    def _parse_season(label):
        if not label:
            return None
        try:
            return int(str(label).split('/')[0])
        except ValueError:
            return None

    @staticmethod
    def _minute_from_clock(clock):
        if not clock:
            return 0
        secs = clock.get('secs')
        if secs is None:
            return 0
        return int(secs // 60)
