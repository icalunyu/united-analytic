"""Bandingin nilai pemain hitungan sendiri (PS-03) sama rating FotMob.

**Bukan buat menyalin rating FotMob.** Desain PS-03 minta nilai yang dihitung
dari event laga, dan itu yang `matches/ratings.py` kerjakan. Command ini cuma
menanyakan satu hal: apakah SKALA kita masuk akal — rata-rata, sebaran, dan
ujung-ujungnya — dibanding penilai profesional yang independen.

Bacanya dari kolom `PlayerMatchStatistics.rating` yang diisi `pull_fotmob`,
jadi nggak nyentuh jaringan sama sekali.

    python manage.py calibrate_ratings
    python manage.py calibrate_ratings --semua-posisi   # ikutkan yang posisinya kosong

**Kenapa default-nya cuma pemain yang posisinya diketahui.** Pemain tanpa
`position` jatuh ke kelompok TENGAH lewat default `ratings.kelompok()`. Di
data lokal itu 243 dari 377 baris — mayoritas pemain lawan yang posisinya
belum pernah kita tarik. Membandingkan mereka berarti menilai bek dan kiper
pakai bobot gelandang, lalu menyalahkan bobotnya waktu hasilnya meleset.

**Kenapa uji silangnya dibelah PER LAGA, bukan per baris.** Pemain di laga
yang sama berbagi konteks — lawan yang sama, skor yang sama, wasit yang sama.
Membelah per baris bikin rekan setim si pemain uji ikut masuk data latih, dan
angka "perbaikan" yang keluar jadi terlalu bagus.
"""

import statistics as st
from collections import defaultdict

from django.core.management.base import BaseCommand

from matches import ratings
from matches.models import PlayerMatchStatistics

# Rentang faktor yang dicoba waktu `--cari`. `k_neg` mengalikan seluruh bobot
# negatif, `k_gk` mengalikan bobot kiper — dua dugaan yang paling masuk akal
# kalau skalanya memang meleset.
RENTANG_K_NEG = [round(0.5 + i * 0.1, 2) for i in range(1, 41)]
RENTANG_K_GK = [round(0.5 + i * 0.1, 2) for i in range(1, 31)]


def _skor(stat, k_neg=1.0, k_gk=1.0):
    kel = ratings.kelompok(stat.player.position)
    skor = ratings.DASAR
    for kolom, w in ratings.BOBOT[kel].items():
        v = getattr(stat, kolom, None)
        if v is None and kolom in ratings.PASANGAN_SETARA:
            v = getattr(stat, ratings.PASANGAN_SETARA[kolom], None)
        if not v:
            continue
        if w < 0:
            w *= k_neg
        if kel == 'GK':
            w *= k_gk
        skor += w * v
    return skor


def _rmse(data, k_neg=1.0, k_gk=1.0):
    if not data:
        return float('inf')
    return (
        sum((_skor(s, k_neg, k_gk) - s.rating) ** 2 for s in data) / len(data)
    ) ** 0.5


def _korelasi(xs, ys):
    if len(xs) < 2:
        return None
    try:
        return st.correlation(xs, ys)
    except st.StatisticsError:
        return None


def _belah_per_laga(data, bagian=2):
    per_laga = defaultdict(list)
    for s in data:
        per_laga[s.match_id].append(s)
    lipatan = [[] for _ in range(bagian)]
    for i, m in enumerate(sorted(per_laga)):
        lipatan[i % bagian].extend(per_laga[m])
    return lipatan


def _cari(data):
    terbaik = None
    for k_neg in RENTANG_K_NEG:
        for k_gk in RENTANG_K_GK:
            g = _rmse(data, k_neg, k_gk)
            if terbaik is None or g < terbaik[0]:
                terbaik = (g, k_neg, k_gk)
    return terbaik


class Command(BaseCommand):
    help = (
        'Bandingin nilai pemain PS-03 sama rating FotMob: rata-rata, sebaran, '
        'korelasi, dan berapa yang kepotong langit-langit. Nggak mengubah apa pun.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--semua-posisi',
            action='store_true',
            help='Ikutkan pemain yang `position`-nya kosong (jatuh ke bobot TENGAH).',
        )
        parser.add_argument(
            '--cari',
            action='store_true',
            help=(
                'Cari faktor k_neg/k_gk yang paling pas, lalu UJI SILANG-kan. '
                'Hasilnya cuma dilaporkan — bobotnya nggak pernah ditulis ulang '
                'otomatis. Mengubah bobot itu keputusan manusia.'
            ),
        )

    def handle(self, *args, **options):
        qs = PlayerMatchStatistics.objects.filter(
            rating__isnull=False, minutes_played__gt=0
        ).select_related('player')
        data = [
            s for s in qs if options['semua_posisi'] or s.player.position
        ]
        if not data:
            self.stderr.write(
                'Nggak ada baris yang punya rating FotMob. Jalanin `pull_fotmob` dulu.'
            )
            return

        laga = len({s.match_id for s in data})
        tanpa_posisi = sum(1 for s in data if not s.player.position)
        self.stdout.write(f'{len(data)} baris dari {laga} laga')
        if tanpa_posisi:
            self.stdout.write(
                self.style.WARNING(
                    f'  {tanpa_posisi} di antaranya nggak punya posisi — mereka dinilai '
                    f'pakai bobot TENGAH, jadi angkanya nggak bisa dipakai menyalahkan '
                    f'bobot per posisi.'
                )
            )

        self._laporkan('Sekarang', data)

        self.stdout.write('\nPer kelompok posisi:')
        per_kel = defaultdict(list)
        for s in data:
            per_kel[ratings.kelompok(s.player.position)].append(s)
        for kel, baris in sorted(per_kel.items()):
            kita = [_skor(s) for s in baris]
            fm = [s.rating for s in baris]
            self.stdout.write(
                f'  {kel:<7} n={len(baris):<4} '
                f'selisih={st.fmean(a - b for a, b in zip(kita, fm)):+.2f} '
                f'sd={st.pstdev(kita):.2f}/{st.pstdev(fm):.2f}'
            )

        if options['cari']:
            self._cari_dan_uji(data)

    def _laporkan(self, nama, data, k_neg=1.0, k_gk=1.0):
        kita = [_skor(s, k_neg, k_gk) for s in data]
        fm = [s.rating for s in data]
        terpotong = sum(1 for x in kita if x > ratings.MAKS_NILAI or x < ratings.MIN_NILAI)
        r = _korelasi(kita, fm)
        self.stdout.write(
            f'\n{nama}: rmse={_rmse(data, k_neg, k_gk):.3f} '
            f'r={r:.3f}\n' if r is not None else f'\n{nama}:\n'
        )
        self.stdout.write(
            f'  rata-rata  kita {st.fmean(kita):.2f}  FotMob {st.fmean(fm):.2f}\n'
            f'  simpangan  kita {st.pstdev(kita):.2f}  FotMob {st.pstdev(fm):.2f}\n'
            f'  terendah   kita {min(kita):.2f}  FotMob {min(fm):.2f}\n'
            f'  tertinggi  kita {max(kita):.2f}  FotMob {max(fm):.2f}\n'
            f'  kepotong langit-langit: {terpotong} dari {len(data)}'
        )

    def _cari_dan_uji(self, data):
        self.stdout.write('\n--- cari faktor + uji silang dua lipatan (dibelah per laga) ---')
        g, kn, kg = _cari(data)
        self.stdout.write(f'Faktor terbaik di SELURUH data: k_neg={kn} k_gk={kg} (rmse {g:.3f})')

        lipatan = _belah_per_laga(data, 2)
        stabil = True
        faktor = []
        for i in range(2):
            latih, uji = lipatan[i], lipatan[1 - i]
            if not latih or not uji:
                continue
            _, kn_i, kg_i = _cari(latih)
            faktor.append((kn_i, kg_i))
            sebelum, sesudah = _rmse(uji, 1.0, 1.0), _rmse(uji, kn_i, kg_i)
            tanda = 'membaik' if sesudah < sebelum else 'MEMBURUK'
            self.stdout.write(
                f'  lipatan {i}: latih k_neg={kn_i} k_gk={kg_i} → '
                f'uji rmse {sebelum:.3f} jadi {sesudah:.3f} ({tanda})'
            )
            if sesudah >= sebelum:
                stabil = False

        if len(faktor) == 2:
            beda_gk = abs(faktor[0][1] - faktor[1][1])
            if beda_gk > 0.5:
                stabil = False
                self.stdout.write(
                    f'  Dua lipatan nggak sepakat soal k_gk ({faktor[0][1]} vs '
                    f'{faktor[1][1]}) — itu tanda faktornya lagi mengejar derau, '
                    f'bukan pola.'
                )

        if stabil:
            self.stdout.write(
                self.style.WARNING(
                    '\nKedua lipatan sepakat DAN membaik di data yang nggak dilatih. '
                    'Ini alasan yang layak buat mempertimbangkan ubah bobot — '
                    'tapi ubahnya tetap manual, di matches/ratings.py.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    '\nKalibrasi ulang TIDAK dianjurkan: perbaikannya nggak bertahan '
                    'di data yang nggak dilatih. Bobot sekarang dipertahankan.'
                )
            )
