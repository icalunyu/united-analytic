"""Narik statistik pemain, statistik tim, shotmap, dan momentum dari FotMob.

Ini penambahan data terbesar yang tersedia gratis buat proyek ini. Yang cuma
ada di sini dan nggak ada di provider lain:

- Aksi bertahan PER PEMAIN (tackles, interceptions, recoveries, dribbled past)
- Umpan dipisah paruh sendiri vs paruh lawan -> bikin PPDA bisa dihitung
- xGOT (kualitas eksekusi) + titik lintasan bola di mulut gawang
- Kurva momentum per menit, buat pembanding model kita sendiri

Cakupan: kompetisi resmi. Laga persahabatan biasanya dapat statistik pemain
tapi TANPA momentum dan shotmap — command ini nanganin itu tanpa error.
"""

import time
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import (
    Match,
    MatchIngest,
    MatchMomentum,
    MatchShot,
    MatchTeamStatistics,
    PlayerMatchStatistics,
)
from matches.services import FotMobClient, FotMobError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource

REQUEST_DELAY_SECONDS = 0.8

# key FotMob -> field PlayerMatchStatistics. Sengaja pakai `key` (snake_case
# yang stabil), bukan `title` yang teks tampilan dan bisa berubah/dilokalkan.
PLAYER_STAT_FIELDS = {
    'rating_title': 'rating',
    'minutes_played': 'minutes_played',
    'goals': 'goals',
    'assists': 'assists',
    'total_shots': 'shots_total',
    'ShotsOnTarget': 'shots_on_target',
    'expected_goals': 'xg',
    'expected_assists': 'xa',
    'chances_created': 'chances_created',
    'accurate_passes': 'passes_accurate',
    'touches': 'touches',
    'touches_opp_box': 'touches_opp_box',
    'passes_into_final_third': 'passes_into_final_third',
    'long_balls_accurate': 'long_balls_accurate',
    'dispossessed': 'dispossessed',
    'defensive_actions': 'defensive_actions',
    'matchstats.headers.tackles': 'tackles',
    'shot_blocks': 'blocks',
    'clearances': 'clearances',
    'interceptions': 'interceptions',
    'recoveries': 'recoveries',
    'dribbled_past': 'dribbled_past',
    'duel_won': 'duels_won',
    'duel_lost': 'duels_lost',
    'ground_duels_won': 'ground_duels_won',
    'aerials_won': 'aerial_duels_won',
    'dribbles_succeeded': 'dribbles_succeeded',
    'fouls': 'fouls_committed',
    'was_fouled': 'fouls_suffered',
    'Offsides': 'offsides',
    'saves': 'saves',
    'goals_conceded': 'goals_conceded',
    'goals_prevented': 'goals_prevented',
    'expected_goals_on_target_faced': 'xgot_faced',
}

TEAM_STAT_FIELDS = {
    'BallPossesion': 'possession_pct',
    'total_shots': 'shots_total',
    'ShotsOnTarget': 'shots_on_target',
    'ShotsOffTarget': None,
    'blocked_shots': 'shots_blocked',
    'corners': 'corners',
    'Offsides': 'offsides',
    'yellow_cards': 'yellow_cards',
    'red_cards': 'red_cards',
    'fouls': 'fouls',
    'passes': 'passes_total',
    'accurate_passes': 'passes_accurate',
    'own_half_passes': 'passes_own_half',
    'opposition_half_passes': 'passes_opposition_half',
    'touches_opp_box': 'touches_opp_box',
    'big_chance': 'big_chances',
    'big_chance_missed_title': 'big_chances_missed',
    'matchstats.headers.tackles': 'tackles_total',
    'interceptions': 'interceptions',
    'clearances': 'clearances_total',
    'keeper_saves': 'saves',
    'duel_won': 'duels_won',
    'dribbles_succeeded': 'dribbles_succeeded',
    'long_balls_accurate': 'long_balls_accurate',
    'accurate_crosses': 'crosses_accurate',
    'expected_goals': 'xg',
    'expected_goals_open_play': 'xg_open_play',
    'expected_goals_set_play': 'xg_set_play',
    'expected_goals_non_penalty': 'xg_non_penalty',
    'expected_goals_on_target': 'xgot',
}

FLOAT_FIELDS = {
    'rating', 'xg', 'xa', 'goals_prevented', 'xgot_faced',
    'xg_open_play', 'xg_set_play', 'xg_non_penalty', 'xgot',
}


class Command(BaseCommand):
    help = 'Narik statistik pemain/tim, shotmap, dan momentum MU dari FotMob.'

    def add_arguments(self, parser):
        parser.add_argument('--team-id', type=str, default=None)
        parser.add_argument('--match-id', type=str, default=None, help='Satu match FotMob saja')
        parser.add_argument('--limit', type=int, default=None, help='Batasi jumlah laga')
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Tarik ulang laga yang sudah pernah ditarik (default: dilewati).',
        )
        parser.add_argument(
            '--league',
            action='store_true',
            help='Seluruh Premier League, bukan cuma laga MU. Bahan tolok ukur se-liga.',
        )
        parser.add_argument(
            '--season',
            type=str,
            default=None,
            help="Format '2025/2026'. Cuma dipakai bareng --league.",
        )

    def handle(self, *args, **options):
        client = FotMobClient()

        if options['match_id']:
            fixture_ids = [options['match_id']]
        else:
            try:
                fixtures = (
                    client.get_league_fixtures(season=options['season'])
                    if options['league']
                    else client.get_team_fixtures(options['team_id'])
                )
            except FotMobError as exc:
                self.stdout.write(self.style.ERROR(f'Gagal narik daftar laga: {exc}'))
                return
            # Laga yang belum main nggak punya statistik apa pun.
            fixture_ids = [
                f['id'] for f in fixtures if (f.get('status') or {}).get('finished')
            ]
            # Urut dari yang terbaru: kalau backfill-nya dipotong --limit atau
            # kena masalah di tengah, yang paling relevan udah masuk duluan.
            fixture_ids.reverse()
            if options['limit']:
                fixture_ids = fixture_ids[: options['limit']]

        self.stdout.write(f'{len(fixture_ids)} laga selesai bakal diproses')

        totals = {'match': 0, 'player': 0, 'team': 0, 'shot': 0, 'momentum': 0, 'slot': 0}
        skipped = 0
        already = 0

        for fixture_id in fixture_ids:
            # Penyaring HARUS sebelum request — yang mahal itu panggilan API,
            # bukan pemrosesannya. Pemetaan id FotMob -> Match dibaca dari
            # MatchExternalRef, jadi nggak perlu nembak jaringan buat tahu
            # laga ini sudah pernah ditarik apa belum.
            if not options['refresh'] and self._already_ingested(fixture_id):
                already += 1
                continue

            try:
                detail = client.get_match(fixture_id)
            except FotMobError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik {fixture_id}: {exc}'))
                continue

            match = self._resolve_match(detail)
            if match is None:
                skipped += 1
                continue
            totals['match'] += 1

            content = detail.get('content') or {}
            totals['player'] += self._save_player_stats(match, content.get('playerStats') or {})
            totals['slot'] += self._save_formation_slots(match, content.get('lineup') or {})
            totals['team'] += self._save_team_stats(match, content.get('stats') or {})
            totals['shot'] += self._save_shots(match, content.get('shotmap'))
            totals['momentum'] += self._save_momentum(match, content.get('momentum'))

            MatchIngest.objects.update_or_create(
                match=match,
                source=DataSource.FOTMOB,
                defaults={'rows': totals['player'] + totals['shot'] + totals['momentum']},
            )
            time.sleep(REQUEST_DELAY_SECONDS)

        if already:
            self.stdout.write(f'{already} laga dilewati (sudah pernah ditarik, pakai --refresh buat paksa).')
        if skipped:
            self.stdout.write(
                self.style.WARNING(f'{skipped} laga nggak ketemu padanannya di database.')
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Selesai. {totals['match']} laga · {totals['player']} statistik pemain · "
                f"{totals['slot']} slot formasi · {totals['team']} statistik tim · "
                f"{totals['shot']} tembakan · {totals['momentum']} titik momentum."
            )
        )

    # ---------------------------------------------------------------- resolve

    @staticmethod
    def _already_ingested(fixture_id):
        """Cek tanpa nyentuh jaringan: id FotMob -> Match -> catatan ingest."""
        try:
            external_id = int(fixture_id)
        except (TypeError, ValueError):
            return False
        return MatchIngest.objects.filter(
            source=DataSource.FOTMOB,
            match__external_refs__source=DataSource.FOTMOB,
            match__external_refs__external_id=external_id,
        ).exists()

    def _resolve_match(self, detail):
        general = detail.get('general') or {}
        home, away = general.get('homeTeam') or {}, general.get('awayTeam') or {}
        if not home.get('id') or not away.get('id'):
            return None

        home_team, _ = resolve_team(
            source=DataSource.FOTMOB,
            external_id=int(home['id']),
            defaults={'name': home.get('name', '')},
        )
        away_team, _ = resolve_team(
            source=DataSource.FOTMOB,
            external_id=int(away['id']),
            defaults={'name': away.get('name', '')},
        )

        kickoff = general.get('matchTimeUTCDate')
        if not kickoff:
            return None
        kickoff_at = timezone.make_aware(
            datetime.strptime(kickoff[:19], '%Y-%m-%dT%H:%M:%S'), dt_timezone.utc
        )

        # Buat laga MU, skor biasanya udah diisi ESPN/football-data. Buat laga
        # liga lain nggak ada provider lain yang nyentuh — kalau nggak diisi di
        # sini, hasilnya Match tanpa skor dan tanpa status.
        header = detail.get('header') or {}
        defaults = {}
        scores = [t.get('score') for t in (header.get('teams') or [])]
        if len(scores) == 2 and all(s is not None for s in scores):
            defaults['home_score'], defaults['away_score'] = scores[0], scores[1]

        status = header.get('status') or {}
        if status.get('cancelled'):
            defaults['status'] = Match.Status.CANCELLED
        elif status.get('finished'):
            defaults['status'] = Match.Status.FINISHED
        elif status.get('started'):
            defaults['status'] = Match.Status.LIVE

        league = (general.get('leagueName') or '')[:150]
        if league:
            defaults['league_name'] = league

        match, _ = resolve_match(
            source=DataSource.FOTMOB,
            external_id=int(general['matchId']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults=defaults,
        )
        return match

    # ------------------------------------------------------------------ stats

    def _save_player_stats(self, match, player_stats):
        saved = 0
        for entry in player_stats.values():
            if not entry.get('id'):
                continue
            team = self._team_from_fotmob_id(match, entry.get('teamId'))
            if team is None:
                continue

            player, _ = resolve_player(
                source=DataSource.FOTMOB,
                external_id=int(entry['id']),
                team=team,
                defaults={'name': entry.get('name', ''), 'team': team},
            )

            values = {}
            for group in entry.get('stats') or []:
                for raw in (group.get('stats') or {}).values():
                    key = (raw or {}).get('key')
                    field = PLAYER_STAT_FIELDS.get(key)
                    if not field:
                        continue
                    value = self._coerce(((raw.get('stat') or {}).get('value')), field)
                    if value is not None:
                        values[field] = value

            if not values:
                continue

            values['team'] = team
            PlayerMatchStatistics.objects.update_or_create(
                match=match, player=player, defaults=values
            )
            saved += 1
        return saved

    def _save_formation_slots(self, match, lineup):
        """Simpen koordinat slot formasi buat starting eleven.

        Cuma meng-update baris PlayerMatchStatistics yang udah dibikin
        _save_player_stats — nggak bikin baris baru, karena pemain yang nggak
        punya statistik juga nggak punya apa-apa buat ditampilin.
        """
        saved = 0
        for side in ('homeTeam', 'awayTeam'):
            team_data = lineup.get(side) or {}
            for entry in team_data.get('starters') or []:
                layout = entry.get('horizontalLayout')
                if not entry.get('id') or not isinstance(layout, dict):
                    continue
                x, y = layout.get('x'), layout.get('y')
                if x is None or y is None:
                    continue

                updated = PlayerMatchStatistics.objects.filter(
                    match=match,
                    player__external_refs__source=DataSource.FOTMOB,
                    player__external_refs__external_id=int(entry['id']),
                ).update(formation_x=x, formation_y=y)
                saved += updated
        return saved

    def _save_team_stats(self, match, stats):
        periods = (stats or {}).get('Periods') or {}
        groups = (periods.get('All') or {}).get('stats') or []
        if not groups:
            return 0

        per_side = {'home': {}, 'away': {}}
        for group in groups:
            for item in group.get('stats') or []:
                field = TEAM_STAT_FIELDS.get(item.get('key'))
                if not field or item.get('type') == 'title':
                    continue
                pair = item.get('stats') or []
                if len(pair) != 2:
                    continue
                for side, raw in zip(('home', 'away'), pair):
                    value = self._coerce(raw, field)
                    if value is not None:
                        per_side[side][field] = value

        saved = 0
        for side, team in (('home', match.home_team), ('away', match.away_team)):
            if per_side[side]:
                MatchTeamStatistics.objects.update_or_create(
                    match=match, team=team, defaults=per_side[side]
                )
                saved += 1
        return saved

    def _save_shots(self, match, shotmap):
        # Laga persahabatan sering dapet `shotmap` kosong atau False.
        shots = (shotmap or {}).get('shots') if isinstance(shotmap, dict) else None
        if not shots:
            return 0

        MatchShot.objects.filter(match=match, source=DataSource.FOTMOB).delete()

        rows = {}
        for shot in shots:
            shot_id = shot.get('id')
            if not shot_id or shot_id in rows:
                continue
            team = self._team_from_fotmob_id(match, shot.get('teamId'))
            if team is None:
                continue

            player = None
            if shot.get('playerId'):
                player, _ = resolve_player(
                    source=DataSource.FOTMOB,
                    external_id=int(shot['playerId']),
                    team=team,
                    defaults={'name': shot.get('playerName', '') or '', 'team': team},
                )

            rows[shot_id] = MatchShot(
                match=match,
                team=team,
                player=player,
                source=DataSource.FOTMOB,
                external_id=str(shot_id),
                minute=shot.get('min') or 0,
                xg=float(shot.get('expectedGoals') or 0),
                xgot=shot.get('expectedGoalsOnTarget'),
                result=shot.get('eventType', '') or '',
                situation=shot.get('situation', '') or '',
                shot_type=shot.get('shotType', '') or '',
                x=shot.get('x'),
                y=shot.get('y'),
                is_on_target=shot.get('isOnTarget'),
                is_blocked=shot.get('isBlocked'),
                is_from_inside_box=shot.get('isFromInsideBox'),
                goal_crossed_y=shot.get('goalCrossedY'),
                goal_crossed_z=shot.get('goalCrossedZ'),
            )

        MatchShot.objects.bulk_create(rows.values())
        return len(rows)

    def _save_momentum(self, match, momentum):
        # `momentum` bisa berupa False buat laga yang nggak dianalisis FotMob.
        if not isinstance(momentum, dict):
            return 0
        points = ((momentum.get('main') or {}).get('data')) or []
        if not points:
            return 0

        MatchMomentum.objects.filter(match=match, source=DataSource.FOTMOB).delete()
        MatchMomentum.objects.bulk_create(
            [
                MatchMomentum(
                    match=match,
                    source=DataSource.FOTMOB,
                    minute=p['minute'],
                    value=p['value'],
                )
                for p in points
                if p.get('minute') is not None and p.get('value') is not None
            ]
        )
        return len(points)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _team_from_fotmob_id(match, team_id):
        """Cocokin teamId FotMob ke home/away lewat external ref yang barusan
        dibikin di _resolve_match."""
        if team_id is None:
            return None
        from players.models import TeamExternalRef

        ref = TeamExternalRef.objects.filter(
            source=DataSource.FOTMOB, external_id=int(team_id)
        ).first()
        if ref is None:
            return None
        if ref.team_id == match.home_team_id:
            return match.home_team
        if ref.team_id == match.away_team_id:
            return match.away_team
        return None

    @staticmethod
    def _coerce(value, field):
        """FotMob campur tipe: angka polos, string desimal, dan bentuk
        '415 (86%)' buat yang punya persentase. Yang diambil selalu angka
        pertama — persentasenya dihitung ulang dari angka mentah kalau perlu."""
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get('total')
            if value is None:
                return None
        text = str(value).strip()
        if not text:
            return None
        head = text.split('(')[0].strip().replace('%', '')
        try:
            number = float(head)
        except ValueError:
            return None
        return number if field in FLOAT_FIELDS else int(round(number))
