import time
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.dedup import resolve_match
from matches.models import Match, MatchIngest, MatchShot, PlayerMatchStatistics
from matches.services import UnderstatClient, UnderstatError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource
from players.provenance import resolve_updates

# Understat nggak nyantumin rate limit resmi. Jeda kecil antar match biar
# nggak ngebanjirin server orang — 38 match jadi ~30 detik, masih aman buat
# cron harian.
REQUEST_DELAY_SECONDS = 0.8


class Command(BaseCommand):
    help = (
        'Narik xG level tembakan + xG/xA/xGChain per pemain dari Understat. '
        'Cuma cover Premier League (Understat nggak punya data kompetisi cup).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--season', type=str, default=None, help='Contoh: 2025')
        parser.add_argument(
            '--team', type=str, default=None, help='Nama tim di Understat, mis. "Manchester United"'
        )
        parser.add_argument(
            '--limit', type=int, default=None, help='Batasi jumlah match (buat tes cepat)'
        )
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Tarik ulang match yang sudah pernah ditarik (default: dilewati).',
        )

    def handle(self, *args, **options):
        client = UnderstatClient()

        try:
            fixtures = client.get_team_matches(
                team_name=options['team'], season=options['season']
            )
        except UnderstatError as exc:
            self.stdout.write(self.style.ERROR(f'Gagal narik daftar match: {exc}'))
            return

        # Match yang belum kelar nggak punya xG — nggak usah dipanggil.
        played = [f for f in fixtures if f.get('isResult')]
        if options['limit']:
            played = played[-options['limit'] :]

        self.stdout.write(f'{len(played)} match selesai dari {len(fixtures)} fixture')

        shots_total = 0
        players_total = 0
        matched = 0
        already = 0
        skipped = []

        for fixture in played:
            # Sebelum request: match yang udah kelar datanya final.
            if not options['refresh'] and self._already_ingested(fixture.get('id')):
                already += 1
                continue

            match = self._resolve_match(fixture)
            if match is None:
                skipped.append(fixture)
                continue
            matched += 1

            try:
                detail = client.get_match(fixture['id'])
            except UnderstatError as exc:
                self.stdout.write(self.style.WARNING(f'  gagal narik match {fixture["id"]}: {exc}'))
                continue

            saved_shots = self._save_shots(match, detail.get('shots') or {})
            saved_players = self._save_player_xg(match, detail.get('rosters') or {})
            shots_total += saved_shots
            players_total += saved_players

            MatchIngest.objects.update_or_create(
                match=match,
                source=DataSource.UNDERSTAT,
                defaults={'rows': saved_shots + saved_players},
            )
            time.sleep(REQUEST_DELAY_SECONDS)

        if already:
            self.stdout.write(
                f'{already} match dilewati (sudah pernah ditarik, pakai --refresh buat paksa).'
            )
        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    f'{len(skipped)} match Understat nggak ketemu padanannya di DB '
                    f'(kemungkinan fixture-nya belum ditarik provider lain).'
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {matched} match dicocokkan, {shots_total} tembakan, '
                f'{players_total} statistik pemain disimpan.'
            )
        )

    @staticmethod
    def _already_ingested(understat_id):
        """Cek tanpa nyentuh jaringan, lewat MatchExternalRef."""
        try:
            external_id = int(understat_id)
        except (TypeError, ValueError):
            return False
        return MatchIngest.objects.filter(
            source=DataSource.UNDERSTAT,
            match__external_refs__source=DataSource.UNDERSTAT,
            match__external_refs__external_id=external_id,
        ).exists()

    def _resolve_match(self, fixture):
        """Cocokin match Understat ke Match yang udah ada di DB.

        resolve_match udah punya fallback (home, away, kickoff ±12 jam), jadi
        fixture yang sama dari ESPN/football-data bakal ke-nempel ke row yang
        sama, bukan bikin duplikat.
        """
        home_data, away_data = fixture.get('h') or {}, fixture.get('a') or {}
        if not home_data.get('title') or not away_data.get('title'):
            return None

        home_team, _ = resolve_team(
            source=DataSource.UNDERSTAT,
            external_id=int(home_data['id']),
            defaults={'name': home_data['title']},
        )
        away_team, _ = resolve_team(
            source=DataSource.UNDERSTAT,
            external_id=int(away_data['id']),
            defaults={'name': away_data['title']},
        )

        kickoff_at = timezone.make_aware(
            datetime.strptime(fixture['datetime'], '%Y-%m-%d %H:%M:%S'), dt_timezone.utc
        )
        goals = fixture.get('goals') or {}

        match, _ = resolve_match(
            source=DataSource.UNDERSTAT,
            external_id=int(fixture['id']),
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
            defaults={
                'home_score': self._to_int(goals.get('h')),
                'away_score': self._to_int(goals.get('a')),
                'status': Match.Status.FINISHED,
            },
        )
        return match

    def _save_shots(self, match, shots):
        MatchShot.objects.filter(match=match).delete()

        rows = {}
        for side, entries in shots.items():
            team = match.home_team if side == 'h' else match.away_team
            for shot in entries:
                shot_id = shot.get('id')
                if not shot_id or shot_id in rows:
                    continue

                player = self._resolve_player(shot.get('player_id'), shot.get('player'), team)
                assisted_by = None
                if shot.get('player_assisted'):
                    # Understat nggak kasih ID buat pemberi assist, cuma nama —
                    # jadi dicocokin lewat sistem dedup nama yang udah ada.
                    assisted_by = self._resolve_player_by_name(shot['player_assisted'], team)

                rows[shot_id] = MatchShot(
                    match=match,
                    team=team,
                    player=player,
                    assisted_by=assisted_by,
                    external_id=str(shot_id),
                    minute=self._to_int(shot.get('minute')) or 0,
                    xg=float(shot.get('xG') or 0),
                    result=shot.get('result', '') or '',
                    situation=shot.get('situation', '') or '',
                    shot_type=shot.get('shotType', '') or '',
                    last_action=shot.get('lastAction', '') or '',
                    x=self._to_float(shot.get('X')),
                    y=self._to_float(shot.get('Y')),
                )

        MatchShot.objects.bulk_create(rows.values())
        return len(rows)

    def _save_player_xg(self, match, rosters):
        saved = 0
        for side, entries in rosters.items():
            team = match.home_team if side == 'h' else match.away_team
            for entry in entries.values():
                player = self._resolve_player(
                    entry.get('player_id'), entry.get('player'), team
                )
                if player is None:
                    continue

                # update_or_create, bukan overwrite: baris ini kemungkinan udah
                # diisi ESPN duluan (tembakan, kartu, dll) — di sini cuma
                # nambahin kolom xG yang cuma Understat yang punya.
                row, _ = PlayerMatchStatistics.objects.get_or_create(
                    match=match, player=player, defaults={'team': team}
                )
                updates, sources = resolve_updates(
                    row.field_sources,
                    DataSource.UNDERSTAT,
                    {
                        'minutes_played': self._to_int(entry.get('time')),
                        'xg': self._to_float(entry.get('xG')),
                        'xa': self._to_float(entry.get('xA')),
                        'xg_chain': self._to_float(entry.get('xGChain')),
                        'xg_buildup': self._to_float(entry.get('xGBuildup')),
                        'key_passes': self._to_int(entry.get('key_passes')),
                    },
                )
                if updates:
                    updates['field_sources'] = sources
                    updates['team'] = team
                    PlayerMatchStatistics.objects.filter(pk=row.pk).update(**updates)
                saved += 1
        return saved

    @staticmethod
    def _resolve_player(external_id, name, team):
        if not external_id or not name:
            return None
        player, _ = resolve_player(
            source=DataSource.UNDERSTAT,
            external_id=int(external_id),
            team=team,
            defaults={'name': name, 'team': team},
        )
        return player

    @staticmethod
    def _resolve_player_by_name(name, team):
        from players.models import Player
        from players.name_utils import player_names_match

        return next(
            (p for p in Player.objects.filter(team=team) if player_names_match(p.name, name)),
            None,
        )

    @staticmethod
    def _to_int(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
