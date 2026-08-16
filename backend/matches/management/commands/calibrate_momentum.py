"""Bandingin kurva momentum model sendiri sama attack momentum Sofascore.

⚠️  ALAT LOKAL — JANGAN DIJADWALIN DI CRON, JANGAN DIPAKAI DI PRODUKSI.

Sofascore ngebatasi akses otomatis di ToS mereka dan endpoint-nya dijagain
Cloudflare, jadi ini cuma buat dijalanin sesekali dari komputer sendiri pas
mau nyetel bobot di `matches/momentum.py`. Data yang dilayanin ke user tetep
100% dari model sendiri (sumbernya ESPN), nggak pernah dari sini.

Cara pakai:
    python manage.py calibrate_momentum --match 241 --sofascore-event 12436870

ID event Sofascore diambil manual dari URL match di situs mereka.
"""

import requests
from django.core.management.base import BaseCommand, CommandError

from matches.models import Match
from matches.momentum import build_momentum

SOFASCORE_GRAPH_URL = 'https://api.sofascore.com/api/v1/event/{event_id}/graph'
BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
)


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
    help = 'ALAT LOKAL: bandingin kurva momentum sendiri vs Sofascore buat nyetel bobot.'

    def add_arguments(self, parser):
        parser.add_argument('--match', type=int, required=True, help='ID Match di database kita')
        parser.add_argument(
            '--sofascore-event', type=str, required=True, help='ID event di Sofascore'
        )

    def handle(self, *args, **options):
        try:
            match = Match.objects.get(pk=options['match'])
        except Match.DoesNotExist:
            raise CommandError(f'Match {options["match"]} nggak ada di database.')

        ours = build_momentum(match)
        if not ours:
            raise CommandError(
                f'{match} belum punya data play — jalanin pull_match_events_espn dulu.'
            )

        theirs = self._fetch_sofascore(options['sofascore_event'])

        # Sofascore ngasih 1 titik per menit juga, tapi skalanya beda dan
        # tandanya bisa kebalik (tergantung tim mana yang mereka anggap
        # "home"). Dicocokin per menit dulu, baru dihitung korelasinya.
        theirs_by_minute = {p['minute']: p['value'] for p in theirs}
        pairs = [
            (row['value'], theirs_by_minute[row['minute']])
            for row in ours
            if row['minute'] in theirs_by_minute
        ]
        if not pairs:
            raise CommandError('Nggak ada menit yang beririsan — cek ID event-nya.')

        mine = [p[0] for p in pairs]
        sofa = [p[1] for p in pairs]
        corr = pearson(mine, sofa)

        self.stdout.write(f'{match}')
        self.stdout.write(f'  menit beririsan   : {len(pairs)}')
        self.stdout.write(f'  rentang kita      : {min(mine):.1f} .. {max(mine):.1f}')
        self.stdout.write(f'  rentang Sofascore : {min(sofa):.1f} .. {max(sofa):.1f}')

        if corr is None:
            self.stdout.write(self.style.WARNING('  korelasi nggak bisa dihitung (data datar).'))
            return

        self.stdout.write(f'  korelasi Pearson  : {corr:+.3f}')
        if corr < 0:
            self.stdout.write(
                self.style.WARNING(
                    '  Korelasi negatif — kemungkinan besar tanda home/away kebalik, '
                    'bukan modelnya yang salah.'
                )
            )
        elif corr >= 0.6:
            self.stdout.write(self.style.SUCCESS('  Bentuk kurvanya udah sejalan.'))
        else:
            self.stdout.write(
                self.style.WARNING(
                    '  Masih lemah — coba setel PLAY_WEIGHTS / DECAY_FORWARD di '
                    'matches/momentum.py, terutama bobot foul & corner.'
                )
            )

    def _fetch_sofascore(self, event_id):
        url = SOFASCORE_GRAPH_URL.format(event_id=event_id)
        try:
            response = requests.get(url, headers={'User-Agent': BROWSER_UA}, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise CommandError(
                f'Gagal ngambil data Sofascore ({exc}).\n'
                'Endpoint ini dijagain Cloudflare dan sering nolak IP datacenter — '
                'jalanin dari koneksi rumah, bukan dari server.'
            ) from exc
        except ValueError as exc:
            raise CommandError(f'Response Sofascore bukan JSON: {exc}') from exc

        points = payload.get('graphPoints') or []
        if not points:
            raise CommandError('Sofascore nggak punya data momentum buat match ini.')
        return points
