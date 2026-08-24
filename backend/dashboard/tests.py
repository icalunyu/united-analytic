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


class StatistikTests(TestCase):
    """Halaman Statistik — Tahap 2 handoff.

    Kriteria selesai dari handoff: *"filter musim dan kompetisi menghasilkan
    angka yang cocok dengan hitungan manual dari data laga."* Test di kelas ini
    yang membuktikannya.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta

        from matches.models import PlayerMatchStatistics
        from players.models import Player

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        cls.lawan = Team.objects.create(name='Ipswich')
        cls.p1 = Player.objects.create(name='Bruno Fernandes', team=cls.mu, position='CM')
        cls.p2 = Player.objects.create(name='Senne Lammens', team=cls.mu, position='GK')
        now = timezone.now()

        def laga(hari, season, liga):
            return Match.objects.create(
                home_team=cls.mu, away_team=cls.lawan,
                kickoff_at=now - timedelta(days=hari),
                season=season, league_name=liga, status=Match.Status.FINISHED,
            )

        cls.liga1 = laga(10, 2026, '2026-27 English Premier League')
        cls.liga2 = laga(20, 2026, '2026-27 English Premier League')
        cls.piala = laga(30, 2026, '2026-27 English FA Cup')
        cls.musim_lalu = laga(400, 2025, '2025-26 English Premier League')

        # Bruno: 90+90 menit di liga, 45 di piala.
        for m, menit, gol in ((cls.liga1, 90, 1), (cls.liga2, 90, 2), (cls.piala, 45, 0)):
            PlayerMatchStatistics.objects.create(
                match=m, player=cls.p1, team=cls.mu, minutes_played=menit, goals=gol,
                assists=1, interceptions=2, passes_accurate=45, passes_total=50,
                passes_into_final_third=6,
            )
        PlayerMatchStatistics.objects.create(
            match=cls.musim_lalu, player=cls.p1, team=cls.mu, minutes_played=90, goals=9,
        )
        # Lammens: kiper.
        # 6 penyelamatan + 2 kebobolan = 8 tembakan, di atas SAVE_MINIMUM.
        # Halaman ini mengagregasi per MUSIM, jadi ambang 5 itu bar yang rendah.
        PlayerMatchStatistics.objects.create(
            match=cls.liga1, player=cls.p2, team=cls.mu, minutes_played=90,
            saves=6, goals_conceded=2,
        )

    def _baris(self, **params):
        r = self.client.get(reverse('dashboard:statistics'), params)
        self.assertEqual(r.status_code, 200)
        return {b['nama']: b for b in r.context['baris']}, r

    def test_agregat_cocok_dengan_hitungan_manual(self):
        """Kriteria selesai handoff. Bruno: 90+90+45 = 225 menit, 1+2+0 = 3 gol."""
        baris, _ = self._baris(musim=2026)
        bruno = baris['Bruno Fernandes']
        self.assertEqual(bruno['menit'], 225)
        self.assertEqual(bruno['gol'], 3)
        self.assertEqual(bruno['assist'], 3)

    def test_filter_kompetisi_mengubah_angka(self):
        """Handoff: 'Menit dan angka total ikut menyesuaikan.'"""
        liga, _ = self._baris(musim=2026, kompetisi='liga')
        self.assertEqual(liga['Bruno Fernandes']['menit'], 180)
        self.assertEqual(liga['Bruno Fernandes']['gol'], 3)

        piala, _ = self._baris(musim=2026, kompetisi='piala')
        self.assertEqual(piala['Bruno Fernandes']['menit'], 45)
        self.assertEqual(piala['Bruno Fernandes']['gol'], 0)

    def test_filter_musim_memisahkan_data(self):
        baris, _ = self._baris(musim=2025)
        self.assertEqual(baris['Bruno Fernandes']['gol'], 9)
        self.assertNotIn('Senne Lammens', baris)

    def test_per90_dihitung_dari_menit_laga_yang_punya_metriknya(self):
        """Bruno: 2 intersep x 3 laga = 6, menit yang punya intersep = 225.
        6 / 225 * 90 = 2.4"""
        baris, _ = self._baris(musim=2026)
        self.assertEqual(baris['Bruno Fernandes']['intersep'], 2.4)

    def test_umpan_persen_dari_akurat_dibagi_total(self):
        """45x3 = 135 akurat dari 50x3 = 150 total -> 90%."""
        baris, _ = self._baris(musim=2026)
        self.assertEqual(baris['Bruno Fernandes']['umpan'], 90.0)

    def test_sv_persen_cuma_buat_kiper(self):
        baris, _ = self._baris(musim=2026)
        self.assertEqual(baris['Senne Lammens']['sv'], 75.0)  # 6/(6+2)
        self.assertIsNone(baris['Bruno Fernandes']['sv'])

    def test_baris_tanpa_data_selalu_di_bawah_di_KEDUA_arah(self):
        """Aturan eksplisit handoff. Nggak bisa dicapai ORDER BY biasa."""
        for arah in ('', 'naik'):
            r = self.client.get(
                reverse('dashboard:statistics'),
                {'musim': 2026, 'urut': 'sv', 'arah': arah},
            )
            nilai = [b['sv'] for b in r.context['baris']]
            kosong_mulai = next(
                (i for i, v in enumerate(nilai) if v is None), len(nilai)
            )
            self.assertTrue(
                all(v is None for v in nilai[kosong_mulai:]),
                f'arah={arah!r}: baris kosong harus mengumpul di bawah, dapat {nilai}',
            )

    def test_cuma_dua_chip_musim(self):
        """Handoff cuma minta 2026/27 dan 2025/26."""
        _, r = self._baris()
        self.assertEqual(len(r.context['musim_tersedia']), 2)

    def test_parameter_ngawur_nggak_bikin_error(self):
        for params in ({'musim': 'xx'}, {'urut': 'kolom-khayalan'},
                       {'kompetisi': 'zzz'}, {'musim': '1999'}):
            self.assertEqual(
                self.client.get(reverse('dashboard:statistics'), params).status_code, 200
            )


class SvPersenHanyaKiperTests(TestCase):
    """Sv% tidak boleh muncul untuk pemain lapangan.

    Regresi: ESPN menulis goals_conceded ke SEMUA baris pemain, bukan cuma
    kiper. Tanpa pagar posisi, bek yang timnya kebobolan 2 dapat Sv% =
    0/(0+2) = 0,0% — dan nol itu kelihatan seperti data.
    """

    @classmethod
    def setUpTestData(cls):
        from matches.models import PlayerMatchStatistics
        from players.models import Player

        mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        m = Match.objects.create(
            home_team=mu, away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now(), season=2026,
            league_name='2026-27 English Premier League', status=Match.Status.FINISHED,
        )
        for nama, pos, saves in (('Harry Maguire', 'CB', 0), ('Senne Lammens', 'GK', 3)):
            PlayerMatchStatistics.objects.create(
                match=m, team=mu, minutes_played=90, saves=saves, goals_conceded=2,
                player=Player.objects.create(name=nama, team=mu, position=pos),
            )

    def test_bek_nggak_dapat_sv_persen(self):
        r = self.client.get(reverse('dashboard:statistics'), {'musim': 2026})
        baris = {b['nama']: b for b in r.context['baris']}
        self.assertIsNone(baris['Harry Maguire']['sv'], 'bek nggak boleh punya Sv%')
        self.assertEqual(baris['Senne Lammens']['sv'], 60.0)


class AmbangSampelTests(TestCase):
    """Persentase dari sampel kecil nggak boleh mendominasi sortir.

    Regresi: waktu halaman ini pertama tayang, Bendito Mantato dengan 14 menit
    nangkring di puncak Umpan% dengan 100% — 1 umpan dari 1. Angkanya benar,
    tapi tabel yang menempatkannya di atas Mainoo (1.623 menit) menyesatkan,
    dan halaman ini dipakai mengutip angka saat siaran.
    """

    @classmethod
    def setUpTestData(cls):
        from matches.models import PlayerMatchStatistics
        from players.models import Player

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        m = Match.objects.create(
            home_team=cls.mu, away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now(), season=2026,
            league_name='2026-27 English Premier League', status=Match.Status.FINISHED,
        )
        # Cameo: 1 umpan dari 1 = 100%.
        PlayerMatchStatistics.objects.create(
            match=m, team=cls.mu, minutes_played=14, passes_accurate=1, passes_total=1,
            player=Player.objects.create(name='Cameo', team=cls.mu, position='CM'),
        )
        # Reguler: 450 dari 500 = 90%.
        PlayerMatchStatistics.objects.create(
            match=m, team=cls.mu, minutes_played=900, passes_accurate=450, passes_total=500,
            player=Player.objects.create(name='Reguler', team=cls.mu, position='CM'),
        )
        # Kiper cameo: 1 penyelamatan, 0 kebobolan = 100%.
        PlayerMatchStatistics.objects.create(
            match=m, team=cls.mu, minutes_played=5, saves=1, goals_conceded=0,
            player=Player.objects.create(name='GK Cameo', team=cls.mu, position='GK'),
        )

    def _baris(self):
        r = self.client.get(reverse('dashboard:statistics'), {'musim': 2026})
        return {b['nama']: b for b in r.context['baris']}

    def test_umpan_persen_sampel_kecil_dikosongkan(self):
        baris = self._baris()
        self.assertIsNone(baris['Cameo']['umpan'], '1 umpan dari 1 bukan 100% yang berarti')
        self.assertEqual(baris['Reguler']['umpan'], 90.0)

    def test_sv_persen_sampel_kecil_dikosongkan(self):
        self.assertIsNone(self._baris()['GK Cameo']['sv'])

    def test_yang_dikosongkan_tetap_di_bawah_saat_sortir(self):
        r = self.client.get(
            reverse('dashboard:statistics'), {'musim': 2026, 'urut': 'umpan'}
        )
        nama = [b['nama'] for b in r.context['baris']]
        self.assertEqual(nama[0], 'Reguler', 'yang punya sampel cukup harus di atas')


class ProvenanceTampilTests(TestCase):
    """Tiga hal yang matang tapi nol dipakai UI, akhirnya tersambung.

    Prinsip desain no. 2: *"Setiap angka membawa sumbernya... Kalau tidak jelas
    asal datanya, jangan ditampilkan."* Datanya 100% terisi di produksi
    (27.824 baris punya field_sources) tapi sebelum ini nggak pernah terlihat
    siapa pun.
    """

    @classmethod
    def setUpTestData(cls):
        from matches.models import FieldConflict, MatchIngest, PlayerMatchStatistics
        from players.models import DataSource, Player

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        cls.m = Match.objects.create(
            home_team=cls.mu, away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now(), season=2026,
            league_name='2026-27 English Premier League', status=Match.Status.FINISHED,
        )
        cls.p = Player.objects.create(name='Bruno Fernandes', team=cls.mu, position='CM')
        PlayerMatchStatistics.objects.create(
            match=cls.m, player=cls.p, team=cls.mu, minutes_played=90, goals=1,
            field_sources={'goals': DataSource.FOTMOB, 'xg': DataSource.UNDERSTAT},
        )
        MatchIngest.objects.create(match=cls.m, source=DataSource.FOTMOB, rows=10)
        FieldConflict.objects.create(
            match=cls.m, player=cls.p, team=cls.mu, field='minutes_played',
            kept_source=DataSource.FOTMOB, kept_value='90',
            other_source=DataSource.ESPN, other_value='87',
        )

    def test_chip_sumber_tampil_di_baris(self):
        r = self.client.get(reverse('dashboard:statistics'), {'musim': 2026})
        baris = {b['nama']: b for b in r.context['baris']}
        self.assertIn('FotMob', baris['Bruno Fernandes']['sumber'])
        self.assertIn('Understat', baris['Bruno Fernandes']['sumber'])
        self.assertContains(r, 'FotMob + Understat')

    def test_kartu_konflik_tampil(self):
        r = self.client.get(reverse('dashboard:statistics'), {'musim': 2026})
        self.assertEqual(len(r.context['konflik']), 1)
        self.assertContains(r, 'Konflik Sumber')
        self.assertContains(r, 'minutes_played')

    def test_kesehatan_sumber_ada_di_semua_halaman(self):
        """Context processor, jadi harus muncul di halaman mana pun."""
        for nama in ('dashboard:home', 'dashboard:schedule', 'dashboard:statistics',
                     'dashboard:squad', 'dashboard:injuries'):
            r = self.client.get(reverse(nama))
            self.assertIn('kesehatan_sumber', r.context, nama)
            self.assertContains(r, 'Kesehatan Sumber', msg_prefix=nama)

    def test_status_feed_dihitung_dari_MatchIngest(self):
        r = self.client.get(reverse('dashboard:home'))
        rows = {s['source']: s for s in r.context['kesehatan_sumber']}
        from players.models import DataSource

        self.assertEqual(rows[DataSource.FOTMOB]['status'], 'normal')
        # Yang belum pernah menarik harus 'berhenti', bukan diam-diam normal.
        self.assertEqual(rows[DataSource.UNDERSTAT]['status'], 'berhenti')


class KartuBebanTests(TestCase):
    """Kartu Beban 14 Hari harus tetap tampil walau semua pemain aman.

    Kartu yang hilang bikin orang nggak bisa bedain "nggak ada yang perlu
    diistirahatkan" dari "fiturnya rusak". Desain LV-08 sendiri punya varian
    'aman', jadi keadaan itu memang bagian dari kartunya.
    """

    @classmethod
    def setUpTestData(cls):
        from players.models import Player

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        Player.objects.create(name='Santai', team=cls.mu, position='CM', is_active=True)

    def test_kartu_tampil_walau_semua_aman(self):
        r = self.client.get(reverse('dashboard:squad'))
        self.assertTrue(r.context['beban_teratas'])
        self.assertFalse(r.context['ada_yang_perlu_diawasi'])
        self.assertContains(r, 'Beban 14 Hari')
        self.assertContains(r, 'semuanya aman')

    def test_rumusnya_disebut_di_halaman(self):
        """Angka skor tanpa rumusnya itu angka telanjang."""
        r = self.client.get(reverse('dashboard:squad'))
        self.assertContains(r, '450')
        self.assertContains(r, 'riwayat cedera otot')
