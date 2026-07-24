from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from matches.services import TheSportsDbError, TheSportsDbClient
from players.dedup import resolve_player, resolve_team
from players.models import DataSource, Player

# TheSportsDB kasih posisi yang jauh lebih spesifik dibanding football-data.org
# (mis. 'Right Winger', 'Defensive Midfield') — mapping ini sengaja lebih rinci.
POSITION_MAP = {
    'Goalkeeper': Player.Position.GOALKEEPER,
    'Centre-Back': Player.Position.CENTRE_BACK,
    'Central Defender': Player.Position.CENTRE_BACK,
    'Defender': Player.Position.CENTRE_BACK,
    'Right-Back': Player.Position.RIGHT_BACK,
    'Left-Back': Player.Position.LEFT_BACK,
    'Defensive Midfield': Player.Position.DEFENSIVE_MIDFIELD,
    'Central Midfield': Player.Position.CENTRAL_MIDFIELD,
    'Midfielder': Player.Position.CENTRAL_MIDFIELD,
    'Attacking Midfield': Player.Position.ATTACKING_MIDFIELD,
    'Right Winger': Player.Position.WINGER,
    'Left Winger': Player.Position.WINGER,
    'Winger': Player.Position.WINGER,
    'Centre-Forward': Player.Position.FORWARD,
    'Forward': Player.Position.FORWARD,
    'Striker': Player.Position.FORWARD,
}


class Command(BaseCommand):
    help = (
        'Narik skuad MU dari TheSportsDB (fallback + posisi lebih rinci '
        'dibanding football-data.org), simpan/update ke database. Cuma nge-'
        'cover sebagian pemain (limitasi free tier), bukan pengganti pull_squad.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=str, default=None, help='Override THESPORTSDB_MU_TEAM_ID dari settings'
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.THESPORTSDB_MU_TEAM_ID
        client = TheSportsDbClient()

        try:
            detail = client.get_team(team_id)
            roster = client.get_roster(team_id)
        except TheSportsDbError as exc:
            raise CommandError(str(exc)) from exc

        if not detail:
            raise CommandError(f'Team id {team_id} nggak ketemu di TheSportsDB.')

        api_football_id = detail.get('idAPIfootball')
        cross_ref = (
            (DataSource.API_FOOTBALL, int(api_football_id))
            if api_football_id and str(api_football_id).isdigit()
            else None
        )

        team, _ = resolve_team(
            source=DataSource.THESPORTSDB,
            external_id=int(team_id),
            defaults={
                'name': detail.get('strTeam', ''),
                'logo_url': detail.get('strBadge', '') or '',
                'is_manchester_united': True,
            },
            cross_ref=cross_ref,
        )

        created_count = 0
        updated_count = 0

        for member in roster:
            _, created = self._save_player(member, team)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(roster)} pemain diproses '
                f'({created_count} baru, {updated_count} update).'
            )
        )

    def _save_player(self, member, team):
        full_name = member.get('strPlayer', '')
        first_name = ''
        last_name = member.get('strLastName', '') or ''
        if last_name and full_name.endswith(last_name):
            first_name = full_name[: -len(last_name)].strip()

        api_football_id = member.get('idAPIfootball')
        cross_ref = (
            (DataSource.API_FOOTBALL, int(api_football_id))
            if api_football_id and str(api_football_id).isdigit()
            else None
        )

        shirt_number = member.get('strNumber')
        height_cm = self._parse_height_cm(member.get('strHeight'))

        position = POSITION_MAP.get(member.get('strPosition'), '')

        player, created = resolve_player(
            source=DataSource.THESPORTSDB,
            external_id=int(member['idPlayer']),
            team=team,
            defaults={
                'name': full_name,
                'first_name': first_name,
                'last_name': last_name,
                'nationality': member.get('strNationality', '') or '',
                'birth_date': member.get('dateBorn') or None,
                'position': position,
                'shirt_number': int(shirt_number) if shirt_number and shirt_number.isdigit() else None,
                'height_cm': height_cm,
                'photo_url': member.get('strCutout', '') or member.get('strThumb', '') or '',
                'team': team,
            },
        )

        # Posisi TheSportsDB jauh lebih rinci (mis. 'Right-Back') dibanding
        # football-data.org (cuma 'Defence') — menang selalu di sini, beda
        # dari field lain yang default-nya isi-kalau-kosong doang.
        if position and player.position != position:
            Player.objects.filter(pk=player.pk).update(position=position)
            player.position = position

        return player, created

    @staticmethod
    def _parse_height_cm(value):
        if not value:
            return None
        # format contoh: "1.83 m" atau "183 cm"
        digits = ''.join(ch for ch in value if ch.isdigit() or ch == '.')
        try:
            number = float(digits)
        except ValueError:
            return None
        return round(number * 100) if number < 3 else round(number)
