from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from matches.services import FootballDataClient, FootballDataError
from players.dedup import resolve_player, resolve_team
from players.models import DataSource, Player

# football-data.org cuma kasih kategori umum, bukan posisi taktis spesifik
# (CB/RB/CDM/winger/dll). Ini cuma starting point kasar — analis tetep perlu
# koreksi manual di admin buat posisi yang lebih presisi.
POSITION_MAP = {
    'Goalkeeper': Player.Position.GOALKEEPER,
    'Defence': Player.Position.CENTRE_BACK,
    'Midfield': Player.Position.CENTRAL_MIDFIELD,
    'Offence': Player.Position.FORWARD,
}


class Command(BaseCommand):
    help = (
        'Narik skuad MU dari football-data.org, simpan/update ke database. '
        'Posisi taktis (CB/RB/CDM/winger/dll) cuma tebakan kasar dari kategori '
        'umum provider — perlu dikoreksi manual di admin.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--team-id', type=int, default=None, help='Override FOOTBALL_DATA_MU_TEAM_ID dari settings'
        )

    def handle(self, *args, **options):
        team_id = options['team_id'] or settings.FOOTBALL_DATA_MU_TEAM_ID

        try:
            client = FootballDataClient()
            data = client.get_team(team_id)
        except FootballDataError as exc:
            raise CommandError(str(exc)) from exc

        team, _ = resolve_team(
            source=DataSource.FOOTBALL_DATA,
            external_id=team_id,
            defaults={
                'name': data.get('name', ''),
                'short_name': data.get('shortName', '') or '',
                'logo_url': data.get('crest', '') or '',
                'is_manchester_united': True,
            },
        )

        squad = data.get('squad', [])
        created_count = 0
        updated_count = 0

        for member in squad:
            _, created = self._save_player(member, team)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {len(squad)} pemain diproses '
                f'({created_count} baru, {updated_count} update).'
            )
        )

    def _save_player(self, member, team):
        full_name = member.get('name', '')
        name_parts = full_name.rsplit(' ', 1)
        first_name = name_parts[0] if len(name_parts) > 1 else ''
        last_name = name_parts[-1] if name_parts else ''

        return resolve_player(
            source=DataSource.FOOTBALL_DATA,
            external_id=member['id'],
            team=team,
            defaults={
                'name': full_name,
                'first_name': first_name,
                'last_name': last_name,
                'nationality': member.get('nationality', '') or '',
                'birth_date': member.get('dateOfBirth') or None,
                'position': POSITION_MAP.get(member.get('position'), ''),
                'team': team,
            },
        )
