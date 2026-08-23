"""Bikin snapshot prediksi susunan MU buat laga berikutnya.

Nggak nyentuh jaringan sama sekali — semua dibaca dari DB, sama kayak
`calibrate_momentum`.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from matches.lineup_prediction import DEFAULT_WINDOW, build_note, predict_xi
from matches.models import LineupSlot, Match, PredictionSnapshot
from players.models import Team


class Command(BaseCommand):
    help = (
        'Bikin PredictionSnapshot berisi prediksi susunan MU buat laga '
        'berikutnya, dihitung dari susunan laga-laga sebelumnya.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--match', type=int, default=None, help='ID laga sasaran')
        parser.add_argument('--window', type=int, default=DEFAULT_WINDOW)
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Beneran tulis snapshot. Tanpa ini cuma dicetak.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Tetap bikin snapshot walau susunannya sama dengan yang terakhir.',
        )

    def handle(self, *args, **options):
        team = self._mu_team()
        match = self._target_match(options['match'])

        if match.kickoff_at <= timezone.now():
            # Bukan mekanisme kunci yang dilarang handoff — nggak ada yang
            # dilarang mengedit apa pun. Ini cuma mencegah cron nulis baris
            # yang PASTI gagal saringan `created_at < kickoff_at` dan cuma
            # jadi sampah di riwayat.
            raise CommandError(
                f'Laga {match} udah kick-off. Prediksi pra-laga nggak bisa '
                f'dibikin belakangan — itu justru inti panel Cek Prediksi.'
            )

        prediksi = predict_xi(team, match.kickoff_at, options['window'])
        self._cetak(match, prediksi)

        if not prediksi['slots']:
            raise CommandError('Nggak ada susunan yang bisa dipakai. Nggak nulis apa-apa.')

        if not options['apply']:
            self.stdout.write(
                self.style.WARNING('\nDRY RUN — nggak ada yang ditulis. Tambahin --apply.')
            )
            return

        if not options['force'] and self._sama_dengan_terakhir(match, prediksi):
            terakhir = match.prediction_snapshots.first()
            self.stdout.write(
                f'\nSusunan sama dengan snapshot {terakhir.created_at:%d %b %H:%M} — '
                f'nggak bikin baris baru. Pakai --force kalau tetap mau.'
            )
            return

        snapshot = self._tulis(match, prediksi, options['window'])
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSnapshot #{snapshot.pk} dibuat {snapshot.created_at:%d %b %Y %H:%M}, '
                f'{snapshot.lead_time()} sebelum kick-off.'
            )
        )

    @staticmethod
    def _mu_team():
        tim = list(Team.objects.filter(is_manchester_united=True))
        if len(tim) != 1:
            raise CommandError(
                f'Ketemu {len(tim)} tim bertanda is_manchester_united, harusnya tepat 1. '
                f'Jalanin merge_duplicates dulu.'
            )
        return tim[0]

    @staticmethod
    def _target_match(match_id):
        if match_id:
            try:
                return Match.objects.get(pk=match_id)
            except Match.DoesNotExist as exc:
                raise CommandError(f'Laga id={match_id} nggak ada.') from exc

        match = (
            Match.objects.filter(
                Q(home_team__is_manchester_united=True)
                | Q(away_team__is_manchester_united=True),
                kickoff_at__gt=timezone.now(),
            )
            .order_by('kickoff_at')
            .first()
        )
        if match is None:
            raise CommandError('Nggak ada laga MU mendatang di database.')
        return match

    def _cetak(self, match, prediksi):
        self.stdout.write(
            f'{match.kickoff_at:%d %b %Y %H:%M} — {match.home_team.name} vs {match.away_team.name}'
        )
        self.stdout.write(
            f'Formasi {prediksi["formation"] or "-"} '
            f'(dasar {prediksi["n_efektif"]} laga)\n'
        )
        for s in prediksi['slots']:
            nama = s['player'].name if s['player'] else '(kosong)'
            yakin = '' if s['confidence_pct'] is None else f'  {s["confidence_pct"]}%'
            tanda = ' *' if s['is_key'] else '  '
            self.stdout.write(
                f'  {s["slot"]:>2}. {s["position"]:<3}{tanda}{nama:<26}'
                f'{s["frekuensi"]:>6}{yakin}'
            )
        if prediksi['warnings']:
            self.stdout.write('')
            for w in prediksi['warnings']:
                self.stdout.write(self.style.WARNING(f'  ! {w}'))
        self.stdout.write(
            '\n  * = pemain kunci (menit terbanyak di jendela). '
            'Persentase = frekuensi historis slot, BUKAN peluang start.'
        )

    @staticmethod
    def _susunan(prediksi):
        return [(s['slot'], s['position'], s['player'].pk if s['player'] else None)
                for s in prediksi['slots']]

    def _sama_dengan_terakhir(self, match, prediksi):
        terakhir = match.prediction_snapshots.first()
        if terakhir is None:
            return False
        lama = [
            (s.slot, s.position, s.player_id)
            for s in terakhir.lineup_slots.all().order_by('slot')
        ]
        return lama == self._susunan(prediksi)

    @staticmethod
    def _tulis(match, prediksi, window):
        snapshot = PredictionSnapshot.objects.create(
            match=match, note=build_note(prediksi, window)
        )
        LineupSlot.objects.bulk_create(
            LineupSlot(
                snapshot=snapshot,
                slot=s['slot'],
                player=s['player'],
                position=s['position'],
                confidence_pct=s['confidence_pct'],
                is_key=s['is_key'],
                pitch_x=s['pitch_x'],
                pitch_y=s['pitch_y'],
            )
            for s in prediksi['slots']
        )
        return snapshot
