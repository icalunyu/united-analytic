import time
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from matches.services import HighlightlyClient, HighlightlyError
from players.models import DataSource, Injury, Player, PlayerExternalRef
from players.name_utils import player_names_match, team_names_match


class Command(BaseCommand):
    help = (
        'Narik riwayat cedera pemain MU dari Highlightly, simpan/update ke '
        'database. Cocokin pemain per nama (inisial + nama belakang) lalu '
        'diverifikasi lewat klub saat ini biar nggak salah orang.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--player', type=str, default=None, help='Filter cuma 1 pemain (cocok sebagian nama)'
        )

    def handle(self, *args, **options):
        try:
            client = HighlightlyClient()
        except HighlightlyError as exc:
            raise CommandError(str(exc)) from exc

        players = Player.objects.filter(team__is_manchester_united=True)
        if options['player']:
            players = players.filter(name__icontains=options['player'])

        if not players.exists():
            raise CommandError(
                'Nggak ada Player MU di database. Jalanin `pull_squad` dulu.'
            )

        matched_count = 0
        skipped_count = 0
        error_count = 0
        injury_count = 0

        for player in players:
            existing_ref = PlayerExternalRef.objects.filter(
                source=DataSource.HIGHLIGHTLY, player=player
            ).first()

            try:
                if existing_ref:
                    # Udah pernah ke-link — langsung ambil detail pakai ID yang
                    # udah ketemu, skip pencarian+verifikasi ulang biar hemat quota.
                    detail = client.get_player(existing_ref.external_id)
                    highlightly_id = existing_ref.external_id
                    detail = detail[0] if isinstance(detail, list) else detail
                else:
                    highlightly_id, detail = self._find_highlightly_player(client, player)
            except HighlightlyError as exc:
                if 'quota harian' in str(exc).lower():
                    raise CommandError(
                        f'{exc} — berhenti, sisanya bakal gagal semua juga. '
                        f'Coba lagi besok atau upgrade plan Highlightly.'
                    ) from exc
                self.stdout.write(self.style.WARNING(f'  error di {player.name}: {exc}'))
                error_count += 1
                continue
            finally:
                time.sleep(0.5)  # jaga-jaga biar nggak burst kena rate limit lagi

            if highlightly_id is None:
                self.stdout.write(f'  lewatin {player.name} — nggak ketemu match yang yakin')
                skipped_count += 1
                continue

            PlayerExternalRef.objects.get_or_create(
                source=DataSource.HIGHLIGHTLY,
                external_id=highlightly_id,
                defaults={'player': player},
            )
            matched_count += 1
            injury_count += self._save_injuries(player, detail.get('injuries') or [])

        if error_count:
            self.stdout.write(self.style.WARNING(f'{error_count} pemain gagal diproses karena error.'))

        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {matched_count} pemain ke-match ({skipped_count} dilewatin), '
                f'{injury_count} entri cedera diproses.'
            )
        )

    def _find_highlightly_player(self, client, player):
        results = client._get('players', {'name': player.name})
        candidates = results.get('data', results) if isinstance(results, dict) else results

        for candidate in candidates:
            candidate_name = candidate.get('fullName') or candidate.get('name') or ''
            if not player_names_match(candidate_name, player.name):
                continue

            detail = client.get_player(candidate['id'])
            detail = detail[0] if isinstance(detail, list) else detail
            club = ((detail.get('profile') or {}).get('club') or {}).get('current', '')

            team_name = player.team.name if player.team else ''
            if club and team_name and team_names_match(club, team_name):
                return candidate['id'], detail

        return None, None

    def _save_injuries(self, player, injuries):
        count = 0
        for entry in injuries:
            start_date = self._parse_date(entry.get('fromDate'))
            if not start_date:
                continue

            end_date = self._parse_date(entry.get('toDate'))
            status = Injury.Status.OUT
            if end_date:
                status = Injury.Status.RETURNED if end_date <= date.today() else Injury.Status.DOUBTFUL

            Injury.objects.update_or_create(
                player=player,
                reason=entry.get('reason', '') or 'Cedera (tidak dirinci)',
                start_date=start_date,
                defaults={
                    'status': status,
                    'expected_return_date': end_date if status == Injury.Status.DOUBTFUL else None,
                    'actual_return_date': end_date if status == Injury.Status.RETURNED else None,
                },
            )
            count += 1
        return count

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%d.%m.%Y').date()
        except ValueError:
            return None
