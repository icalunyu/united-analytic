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

# Ambang aman buat nandain pemain non-aktif. Kalau provider ngebalikin skuad
# lebih kecil dari ini, hampir pasti responsnya kepotong (quota abis, error
# separuh jalan) — dan nandain sisanya non-aktif bakal ngosongin skuad.
# Lebih baik nggak ngapa-ngapain daripada salah.
MIN_SQUAD_FOR_DEACTIVATION = 15


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
        parser.add_argument(
            '--no-deactivate',
            action='store_true',
            help='Jangan tandai pemain di luar skuad sebagai non-aktif.',
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
        squad_ids = set()

        for member in squad:
            player, created = self._save_player(member, team)
            squad_ids.add(player.pk)
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

        self._sync_active_flags(team, squad_ids, skip=options['no_deactivate'])

    def _sync_active_flags(self, team, squad_ids, skip=False):
        """Samain `is_active` sama skuad terkini dari provider.

        Tanpa ini `is_active` nggak pernah disetel siapa pun — defaultnya True
        dan nggak ada yang pernah ngubah — jadi tiap pemain yang pernah
        kecatat di MU (termasuk yang udah pindah bertahun-tahun lalu, dari
        data historis Premier League) selamanya ikut kehitung "Skuad Aktif".
        """
        if skip:
            self.stdout.write('Penandaan non-aktif dilewati (--no-deactivate).')
            return

        if len(squad_ids) < MIN_SQUAD_FOR_DEACTIVATION:
            self.stdout.write(
                self.style.WARNING(
                    f'Cuma {len(squad_ids)} pemain kebaca (minimal {MIN_SQUAD_FOR_DEACTIVATION}) — '
                    f'penandaan non-aktif dilewati biar skuad nggak kekosongan gara-gara '
                    f'respons yang kepotong.'
                )
            )
            return

        # Dua arah, biar bisa mengoreksi diri: yang balik ke skuad diaktifkan
        # lagi, bukan cuma yang keluar dinonaktifkan.
        reactivated = Player.objects.filter(team=team, pk__in=squad_ids, is_active=False).update(
            is_active=True
        )
        deactivated = (
            Player.objects.filter(team=team, is_active=True)
            .exclude(pk__in=squad_ids)
            .update(is_active=False)
        )

        if deactivated or reactivated:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Status skuad disamain: {deactivated} ditandai non-aktif, '
                    f'{reactivated} diaktifkan lagi.'
                )
            )
        else:
            self.stdout.write('Status skuad udah sesuai.')

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
