import time
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from matches.services import HighlightlyClient, HighlightlyError
from players.models import DataSource, Injury, Player, PlayerExternalRef
from players.name_utils import player_names_match, team_names_match

# Tiap pemain yang belum ke-link butuh 1 panggilan pencarian + 1 verifikasi per
# kandidat yang namanya cocok. Tanpa batas, satu nama umum bisa memicu belasan
# verifikasi dan menghabiskan quota buat satu orang saja.
MAX_VERIFY_PER_PLAYER = 3

# Plan gratis Highlightly quota-nya ketat. Angka ini konservatif: skuad aktif MU
# 38 orang, hampir semuanya sudah ke-link (1 panggilan), jadi run normal jauh di
# bawah batas ini. Batasnya ada supaya kasus aneh nggak bikin cron jebol diam-diam.
DEFAULT_MAX_CALLS = 80


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
        parser.add_argument(
            '--include-inactive',
            action='store_true',
            help=(
                'Ikutkan mantan pemain. Default cuma skuad aktif — mantan pemain '
                'nggak pernah ketemu di Highlightly dan cuma ngabisin quota.'
            ),
        )
        parser.add_argument(
            '--max-calls',
            type=int,
            default=DEFAULT_MAX_CALLS,
            help=(
                f'Batas panggilan API dalam satu run (default {DEFAULT_MAX_CALLS}). '
                f'Berhenti rapi sebelum quota harian jebol.'
            ),
        )

    def handle(self, *args, **options):
        try:
            client = HighlightlyClient()
        except HighlightlyError as exc:
            raise CommandError(str(exc)) from exc

        players = Player.objects.filter(team__is_manchester_united=True)
        if not options['include_inactive']:
            # Mantan pemain nggak akan pernah lolos verifikasi klub (klub mereka
            # di Highlightly bukan MU lagi), jadi tiap malam mereka membakar
            # 2+ panggilan cuma buat gagal. Di produksi ini 60 dari 98 pemain.
            players = players.filter(is_active=True)
        if options['player']:
            players = players.filter(name__icontains=options['player'])

        if not players.exists():
            raise CommandError(
                'Nggak ada Player MU di database. Jalanin `pull_squad` dulu.'
            )

        # Yang sudah ke-link diproses duluan: cuma 1 panggilan dan justru merekalah
        # yang datanya kepakai. Kalau quota habis di tengah jalan, yang kepotong
        # adalah pencarian pemain baru, bukan pembaruan cedera skuad inti.
        linked_map = dict(
            PlayerExternalRef.objects.filter(
                source=DataSource.HIGHLIGHTLY, player__in=players
            ).values_list('player_id', 'external_id')
        )
        ordered = sorted(players, key=lambda p: p.id not in linked_map)

        self.budget = options['max_calls']
        matched_count = 0
        skipped_count = 0
        error_count = 0
        injury_count = 0
        exhausted = False

        for player in ordered:
            existing_id = linked_map.get(player.id)
            need = 1 if existing_id else 1 + MAX_VERIFY_PER_PLAYER
            if self.budget < need:
                exhausted = True
                self.stdout.write(
                    self.style.WARNING(
                        f'Batas {options["max_calls"]} panggilan tercapai — '
                        f'berhenti di {player.name}. Sisanya lanjut besok.'
                    )
                )
                break

            try:
                if existing_id:
                    # Udah pernah ke-link — langsung ambil detail pakai ID yang
                    # udah ketemu, skip pencarian+verifikasi ulang biar hemat quota.
                    self.budget -= 1
                    detail = client.get_player(existing_id)
                    highlightly_id = existing_id
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

        used = options['max_calls'] - self.budget
        style = self.style.WARNING if exhausted else self.style.SUCCESS
        self.stdout.write(
            style(
                f'Selesai. {matched_count} pemain ke-match ({skipped_count} dilewatin), '
                f'{injury_count} entri cedera diproses. '
                f'{used}/{options["max_calls"]} panggilan API kepakai.'
            )
        )

    def _find_highlightly_player(self, client, player):
        self.budget -= 1
        results = client._get('players', {'name': player.name})
        candidates = results.get('data', results) if isinstance(results, dict) else results

        verified = 0
        for candidate in candidates:
            candidate_name = candidate.get('fullName') or candidate.get('name') or ''
            if not player_names_match(candidate_name, player.name):
                continue

            # Nama umum ('Danny Ward', 'Harry Wilson') bisa balikin banyak
            # kandidat yang semuanya lolos pencocokan nama. Tanpa batas ini,
            # satu pemain saja bisa menelan belasan panggilan verifikasi.
            if verified >= MAX_VERIFY_PER_PLAYER:
                break
            verified += 1

            self.budget -= 1
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
