"""Nilai hipotesis pra-laga sesudah laganya kelar — inti panel Cek Prediksi.

Handoff nyebut panel ini **pembeda utama produk**: membuktikan analisis dibuat
sebelum laga, bukan setelah fakta. Tanpa command ini, hipotesis yang tersimpan
cuma jadi baris BELUM selamanya.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Sum
from django.utils import timezone

from matches.lineup_prediction import baca_kriteria, read_xi
from matches.models import (
    HypothesisItem,
    Match,
    MatchEvent,
    MatchShot,
    MatchTeamStatistics,
)
from players.models import Team

FINAL = ('FT', 'AET', 'PEN')


class Command(BaseCommand):
    help = 'Nilai hipotesis pra-laga (KENA/MELESET) + akurasi susunan.'

    def add_arguments(self, parser):
        parser.add_argument('--match', type=int, default=None, help='ID laga')
        parser.add_argument(
            '--apply', action='store_true', help='Tulis hasilnya. Tanpa ini cuma dicetak.'
        )
        parser.add_argument(
            '--ulang',
            action='store_true',
            help='Nilai ulang hipotesis yang sudah pernah dinilai.',
        )

    def handle(self, *args, **options):
        match = self._target(options['match'])
        team = Team.objects.get(is_manchester_united=True)

        if match.status not in FINAL:
            raise CommandError(
                f'Laga {match} statusnya {match.status}, belum final. '
                f'Menilai hipotesis di tengah laga bakal ngasih hasil yang berubah '
                f'lagi nanti.'
            )

        snapshot = match.prediction_before_kickoff()
        if snapshot is None:
            raise CommandError(
                f'Nggak ada prediksi pra-kickoff buat {match}. '
                f'Cek Prediksi nggak punya dasar — dan ini nggak bisa ditambal '
                f'belakangan.'
            )

        self.stdout.write(
            f'{match} — prediksi #{snapshot.pk} dibuat '
            f'{snapshot.lead_time} sebelum kick-off\n'
        )

        fakta = self._kumpulkan_fakta(match, team)
        self._cetak_fakta(fakta)

        hasil = []
        for h in snapshot.hypotheses.all():
            if h.outcome != HypothesisItem.Outcome.PENDING and not options['ulang']:
                hasil.append((h, h.outcome, '(sudah dinilai)'))
                continue
            outcome, catatan = self._nilai(h, fakta)
            hasil.append((h, outcome, catatan))

        self.stdout.write('\nHipotesis:')
        for h, outcome, catatan in hasil:
            warna = {
                HypothesisItem.Outcome.HIT: self.style.SUCCESS,
                HypothesisItem.Outcome.MISS: self.style.ERROR,
            }.get(outcome, self.style.WARNING)
            self.stdout.write(f'  {warna(f"[{outcome}]")} {h.text}')
            self.stdout.write(f'        {catatan}')

        akurasi = self._akurasi_susunan(snapshot, match, team)
        self.stdout.write(f'\nAkurasi susunan: {akurasi}')

        if not options['apply']:
            self.stdout.write(
                self.style.WARNING('\nDRY RUN — nggak ada yang ditulis. Tambahin --apply.')
            )
            return

        ditulis = 0
        for h, outcome, catatan in hasil:
            if catatan == '(sudah dinilai)':
                continue
            h.outcome = outcome
            h.outcome_note = catatan[:300]
            h.evaluated_at = timezone.now()
            h.save(update_fields=['outcome', 'outcome_note', 'evaluated_at'])
            ditulis += 1
        self.stdout.write(self.style.SUCCESS(f'\n{ditulis} hipotesis dinilai.'))

    # ------------------------------------------------------------------ data

    @staticmethod
    def _target(match_id):
        if match_id:
            try:
                return Match.objects.get(pk=match_id)
            except Match.DoesNotExist as exc:
                raise CommandError(f'Laga id={match_id} nggak ada.') from exc
        match = (
            Match.objects.filter(
                Q(home_team__is_manchester_united=True)
                | Q(away_team__is_manchester_united=True),
                status__in=FINAL,
                prediction_snapshots__isnull=False,
            )
            .distinct()
            .order_by('-kickoff_at')
            .first()
        )
        if match is None:
            raise CommandError('Nggak ada laga selesai yang punya prediksi.')
        return match

    @staticmethod
    def _kumpulkan_fakta(match, team):
        """Angka yang benar-benar terjadi, buat dibandingkan sama hipotesis."""
        stat = MatchTeamStatistics.objects.filter(match=match, team=team).first()
        formasi = (
            match.home_formation
            if match.home_team_id == team.pk
            else match.away_formation
        )
        xg = MatchShot.objects.filter(match=match, team=team).aggregate(s=Sum('xg'))['s']
        return {
            'formasi': formasi or None,
            'shots_on_target': stat.shots_on_target if stat else None,
            'possession_pct': stat.possession_pct if stat else None,
            'gol': MatchEvent.objects.filter(
                match=match, team=team, event_type=MatchEvent.EventType.GOAL
            ).count(),
            'xg': round(xg, 2) if xg else None,
        }

    def _cetak_fakta(self, fakta):
        self.stdout.write('Yang benar-benar terjadi:')
        for k, v in fakta.items():
            self.stdout.write(f'  {k:<18} {v if v is not None else "(nggak ada data)"}')

    # ---------------------------------------------------------------- menilai

    @staticmethod
    def _nilai(hypothesis, fakta):
        """(outcome, catatan) buat satu hipotesis."""
        kriteria = baca_kriteria(hypothesis.evidence_note)
        if kriteria is None:
            # Kalimat bebas tulisan analis. App nggak pura-pura ngerti.
            return (
                HypothesisItem.Outcome.PENDING,
                'Nggak ada kriteria terbaca-mesin — perlu dinilai manual.',
            )

        metrik, op, ambang = kriteria
        nyata = fakta.get(metrik)
        if nyata is None:
            return (
                HypothesisItem.Outcome.PENDING,
                f'Datanya belum ada buat {metrik} — belum bisa dinilai.',
            )

        if op == '=':
            kena = str(nyata) == str(ambang)
        elif op == '>=':
            kena = float(nyata) >= float(ambang)
        else:
            kena = float(nyata) > float(ambang)

        outcome = (
            HypothesisItem.Outcome.HIT if kena else HypothesisItem.Outcome.MISS
        )
        return outcome, f'{metrik} = {nyata} (syarat {op} {ambang})'

    def _akurasi_susunan(self, snapshot, match, team):
        """Berapa dari 11 slot prediksi yang benar-benar start.

        Dibandingkan ke `formation_x` FotMob, yang baru masuk sesudah
        `pull_fotmob` jalan. Kalau belum ada, jangan ngarang angka.
        """
        slots = snapshot.lineup_slots.all()
        if not slots:
            return '(nggak ada prediksi susunan)'

        nyata = read_xi(match, team)
        if nyata is None:
            return '(susunan sebenarnya belum masuk — jalanin pull_fotmob dulu)'

        id_nyata = {s['player_id'] for s in nyata}
        id_prediksi = {s.player_id for s in slots if s.player_id}
        tepat = len(id_prediksi & id_nyata)
        return f'{tepat} dari {len(slots)} tepat'
