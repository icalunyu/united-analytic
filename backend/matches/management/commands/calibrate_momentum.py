"""Bandingin kurva momentum model sendiri sama momentum FotMob.

Dulu command ini nembak Sofascore dan nggak pernah bisa dites — endpoint
mereka nolak koneksi dari sini maupun dari server. FotMob ngasih data yang
sama bentuknya (satu titik per menit, skala -100..100) dan bisa dijangkau,
jadi kalibrasinya sekarang beneran jalan.

Datanya dibaca dari tabel MatchMomentum yang diisi `pull_fotmob`, bukan
ditarik ulang tiap kali — jadi command ini nggak nyentuh jaringan sama sekali.

    python manage.py pull_fotmob --match-id <id-fotmob>   # sekali, ngisi data
    python manage.py calibrate_momentum --match 241       # bandingin
    python manage.py calibrate_momentum --all             # semua laga yang ada
"""

from django.core.management.base import BaseCommand, CommandError

from matches.models import Match, MatchMomentum
from matches.momentum import build_momentum
from players.models import DataSource


def pearson(xs, ys):
    """Korelasi Pearson tanpa numpy (numpy bukan dependency proyek ini)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    den = (sum(a * a for a in dx) * sum(b * b for b in dy)) ** 0.5
    return num / den if den else None


class Command(BaseCommand):
    help = 'Bandingin momentum model sendiri vs FotMob buat nyetel bobot.'

    def add_arguments(self, parser):
        parser.add_argument('--match', type=int, default=None, help='ID Match di database kita')
        parser.add_argument(
            '--all', action='store_true', help='Semua laga yang punya momentum FotMob'
        )

    def handle(self, *args, **options):
        if options['all']:
            matches = Match.objects.filter(
                momentum_points__source=DataSource.FOTMOB
            ).distinct().order_by('kickoff_at')
        elif options['match']:
            matches = Match.objects.filter(pk=options['match'])
        else:
            raise CommandError('Kasih --match <id> atau --all.')

        if not matches:
            raise CommandError(
                'Nggak ada laga yang punya momentum FotMob. Jalanin pull_fotmob dulu.'
            )

        scores = []
        for match in matches:
            result = self._compare(match)
            if result is not None:
                scores.append(result)

        if len(scores) > 1:
            average = sum(scores) / len(scores)
            self.stdout.write('')
            self.stdout.write(f'Rata-rata korelasi dari {len(scores)} laga: {average:+.3f}')
            self._advise(average)

    def _compare(self, match):
        ours = build_momentum(match)
        if not ours:
            self.stdout.write(self.style.WARNING(f'{match}: belum ada data play, dilewati.'))
            return None

        reference = {
            # Menit FotMob pecahan buat injury time; dibulatkan biar bisa
            # dipasangin sama kurva kita yang per menit bulat.
            round(p.minute): p.value
            for p in MatchMomentum.objects.filter(match=match, source=DataSource.FOTMOB)
        }
        if not reference:
            self.stdout.write(self.style.WARNING(f'{match}: nggak ada momentum FotMob, dilewati.'))
            return None

        pairs = [(r['value'], reference[r['minute']]) for r in ours if r['minute'] in reference]
        if len(pairs) < 2:
            self.stdout.write(self.style.WARNING(f'{match}: menit beririsan terlalu sedikit.'))
            return None

        mine = [p[0] for p in pairs]
        theirs = [p[1] for p in pairs]
        corr = pearson(mine, theirs)
        if corr is None:
            self.stdout.write(self.style.WARNING(f'{match}: kurvanya datar, korelasi nggak ada.'))
            return None

        self.stdout.write(
            f'{match}\n'
            f'  menit beririsan {len(pairs):3d} · rentang kita '
            f'{min(mine):+6.1f}..{max(mine):+6.1f} · FotMob '
            f'{min(theirs):+6.1f}..{max(theirs):+6.1f} · korelasi {corr:+.3f}'
        )
        return corr

    def _advise(self, corr):
        if corr < 0:
            self.stdout.write(
                self.style.WARNING(
                    'Korelasi negatif — kemungkinan besar tanda home/away kebalik, '
                    'bukan modelnya yang salah.'
                )
            )
        elif corr >= 0.6:
            self.stdout.write(self.style.SUCCESS('Bentuk kurvanya udah sejalan.'))
        else:
            self.stdout.write(
                self.style.WARNING(
                    'Masih lemah — setel PLAY_WEIGHTS / DECAY_FORWARD di '
                    'matches/momentum.py, terutama bobot foul & corner.'
                )
            )
