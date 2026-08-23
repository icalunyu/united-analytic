"""Test halaman dashboard.

Sampai sekarang seluruh test di repo ini ada di lapisan data — nol yang
menyentuh view atau template. Tahap berikutnya (halaman Skuad, Statistik,
Berita) 100% kerja view, jadi jaring pertamanya dimulai di sini.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from datetime import timedelta

from matches.models import Match
from players.models import Team


class JadwalFilterTests(TestCase):
    """Filter musim & kompetisi di halaman Jadwal.

    Dulu halaman ini cuma punya toggle `?all=1` yang motong di 100 laga.
    Sesudah backfill 8 musim, ~370 dari 470 laga MU nggak bisa dijangkau lewat
    UI sama sekali.
    """

    @classmethod
    def setUpTestData(cls):
        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        cls.lawan = Team.objects.create(name='Ipswich Town')
        now = timezone.now()

        def laga(hari_lalu, season, league_name, status=Match.Status.FINISHED):
            return Match.objects.create(
                home_team=cls.mu,
                away_team=cls.lawan,
                kickoff_at=now - timedelta(days=hari_lalu),
                season=season,
                league_name=league_name,
                status=status,
                home_score=2,
                away_score=1,
            )

        cls.liga_2025 = laga(10, 2025, '2025-26 English Premier League')
        cls.liga_2024 = laga(400, 2024, '2024-25 English Premier League')
        cls.eropa_2024 = laga(390, 2024, '2024-25 UEFA Europa League')
        cls.piala_2024 = laga(380, 2024, '2024-25 English Carabao Cup')
        cls.friendly = laga(370, 2024, '2024 Club Friendly')
        # Laga mendatang: yang muncul di tampilan awal.
        cls.mendatang = Match.objects.create(
            home_team=cls.mu,
            away_team=cls.lawan,
            kickoff_at=now + timedelta(days=7),
            season=2026,
            league_name='2026-27 English Premier League',
            status=Match.Status.NOT_STARTED,
        )

    def test_tampilan_awal_cuma_mendatang(self):
        """Perilaku lama harus tetap: tanpa filter, yang tampil laga mendatang."""
        r = self.client.get(reverse('dashboard:schedule'))
        self.assertEqual(r.status_code, 200)
        ids = [m.id for m in r.context['matches']]
        self.assertEqual(ids, [self.mendatang.id])
        self.assertFalse(r.context['menyaring'])

    def test_semua_histori_bisa_dijangkau(self):
        r = self.client.get(reverse('dashboard:schedule'), {'all': '1'})
        self.assertEqual(r.context['total'], 6)

    def test_filter_musim(self):
        r = self.client.get(reverse('dashboard:schedule'), {'musim': '2024'})
        ids = {m.id for m in r.context['matches']}
        self.assertEqual(
            ids, {self.liga_2024.id, self.eropa_2024.id, self.piala_2024.id, self.friendly.id}
        )

    def test_filter_kompetisi(self):
        for kunci, harapan in [
            ('liga', {self.liga_2025.id, self.liga_2024.id, self.mendatang.id}),
            ('eropa', {self.eropa_2024.id}),
            ('piala', {self.piala_2024.id}),
            ('persahabatan', {self.friendly.id}),
        ]:
            r = self.client.get(reverse('dashboard:schedule'), {'kompetisi': kunci})
            self.assertEqual({m.id for m in r.context['matches']}, harapan, kunci)

    def test_musim_dan_kompetisi_digabung(self):
        r = self.client.get(
            reverse('dashboard:schedule'), {'musim': '2024', 'kompetisi': 'liga'}
        )
        self.assertEqual({m.id for m in r.context['matches']}, {self.liga_2024.id})

    def test_facet_nggak_ikut_tersaring(self):
        """Pilihan yang lagi aktif nggak boleh menghilangkan pilihan lain.

        Ini juga pagar buat jebakan GROUP BY: Match.Meta punya
        ordering = ['kickoff_at'], dan Django nyeret kolom itu ke GROUP BY
        kalau .order_by() nggak dikosongin — hasilnya satu baris per kickoff
        unik, bukan satu baris per musim.
        """
        r = self.client.get(reverse('dashboard:schedule'), {'musim': '2025'})
        self.assertEqual(r.context['musim_tersedia'], [2026, 2025, 2024])
        self.assertEqual(
            [k['kunci'] for k in r.context['kategori_tersedia']],
            ['liga', 'eropa', 'piala', 'persahabatan'],
        )

    def test_paginasi(self):
        from dashboard.views import PER_HALAMAN

        now = timezone.now()
        for i in range(PER_HALAMAN + 5):
            Match.objects.create(
                home_team=self.mu,
                away_team=self.lawan,
                kickoff_at=now - timedelta(days=1000 + i),
                season=2019,
                league_name='2019-20 English Premier League',
                status=Match.Status.FINISHED,
            )
        r = self.client.get(reverse('dashboard:schedule'), {'musim': '2019'})
        self.assertEqual(len(r.context['matches']), PER_HALAMAN)
        self.assertTrue(r.context['halaman'].has_next)

        r2 = self.client.get(reverse('dashboard:schedule'), {'musim': '2019', 'hal': '2'})
        self.assertEqual(len(r2.context['matches']), 5)

    def test_parameter_ngawur_nggak_bikin_error(self):
        for params in (
            {'musim': 'bukan-angka'},
            {'kompetisi': 'liga-khayalan'},
            {'hal': '999'},
            {'hal': 'abc'},
            {'musim': '2024', 'kompetisi': ''},
        ):
            r = self.client.get(reverse('dashboard:schedule'), params)
            self.assertEqual(r.status_code, 200, params)
