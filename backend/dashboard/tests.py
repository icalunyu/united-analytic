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


class PraLagaTests(TestCase):
    """Halaman Pra-laga — PR-01/02/03/04/05.

    Yang paling penting dijaga: pagar pra-kickoff. Handoff melarang mekanisme
    kunci, jadi yang menegakkan kejujuran panel ini bukan tombol melainkan
    `prediction_before_kickoff()`.
    """

    def setUp(self):
        from datetime import timedelta

        from matches.models import HypothesisItem, LineupSlot, PredictionSnapshot
        from players.models import Player

        self.td = timedelta
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=timezone.now() + timedelta(days=6),
            league_name='2026-27 English Premier League', venue='Old Trafford',
        )
        self.snapshot = PredictionSnapshot.objects.create(match=self.match)
        p = Player.objects.create(name='Senne Lammens', team=self.mu, position='GK')
        LineupSlot.objects.create(
            snapshot=self.snapshot, slot=1, player=p, position='GK',
            confidence_pct=60, is_key=True, pitch_x=0.05, pitch_y=0.5,
        )
        HypothesisItem.objects.create(
            snapshot=self.snapshot, order=1, text='MU turun 4-2-3-1',
            evidence_note='Dasar: 4 dari 5. [cek:formasi=4-2-3-1]',
        )
        self.HypothesisItem = HypothesisItem
        self.PredictionSnapshot = PredictionSnapshot

    def _jadikan_berjalan(self, snapshot_pra_peluit=True):
        """Geser laga jadi sedang berjalan.

        Cap waktu snapshot HARUS ikut digeser. `created_at` itu auto_now_add,
        jadi kalau cuma kickoff yang dimundurkan, snapshot-nya jadi
        PASCA-peluit dan benar-benar ditolak `prediction_before_kickoff()` —
        itu perilaku yang dijaga, bukan bug.
        """
        kickoff = timezone.now() - self.td(minutes=30)
        Match.objects.filter(pk=self.match.pk).update(
            status=Match.Status.LIVE, kickoff_at=kickoff
        )
        self.match.refresh_from_db()
        if snapshot_pra_peluit:
            self.PredictionSnapshot.objects.filter(pk=self.snapshot.pk).update(
                created_at=kickoff - self.td(days=1)
            )

    def _get(self, **params):
        r = self.client.get(reverse('dashboard:pre_match'), params)
        self.assertEqual(r.status_code, 200)
        return r

    def test_mode_menyiapkan_laga_sebelum_kickoff(self):
        r = self._get()
        self.assertFalse(r.context['berjalan'])
        self.assertContains(r, 'Menyiapkan laga')
        self.assertContains(r, 'Hipotesis Taktik')
        self.assertNotContains(r, 'Laga berjalan')

    def test_mode_cek_prediksi_saat_laga_berjalan(self):
        self._jadikan_berjalan()
        r = self._get()
        self.assertTrue(r.context['berjalan'])
        self.assertContains(r, 'Laga berjalan')
        self.assertContains(r, 'Cek Prediksi')

    def test_snapshot_pasca_peluit_TIDAK_dipakai(self):
        """Pagar yang bikin panel ini berarti. Prediksi yang ditulis sesudah
        peluit nggak boleh menyamar jadi prediksi pra-laga."""
        self._jadikan_berjalan(snapshot_pra_peluit=False)
        r = self._get()
        self.assertIsNone(r.context['snapshot'])
        self.assertContains(r, 'Belum ada prediksi tersimpan')

    def test_snapshot_pra_peluit_dipakai(self):
        self._jadikan_berjalan(snapshot_pra_peluit=True)
        r = self._get()
        self.assertEqual(r.context['snapshot'].pk, self.snapshot.pk)

    def test_node_susunan_punya_koordinat(self):
        r = self._get()
        slot = r.context['slots'][0]
        self.assertIn('left:5.0%', slot.gaya)
        self.assertIn('top:50.0%', slot.gaya)

    def test_persentase_dijelaskan_bukan_peluang_start(self):
        """Angka telanjang yang gampang disalahartikan wajib dijelaskan."""
        r = self._get()
        self.assertContains(r, 'frekuensi historis slot')
        self.assertContains(r, 'bukan')

    def test_head_to_head_skor_ditulis_United_dulu(self):
        """Konvensi handoff: MU selalu ditulis lebih dulu, apa pun venue-nya."""
        Match.objects.create(
            home_team=self.lawan, away_team=self.mu,
            kickoff_at=timezone.now() - self.td(days=200),
            status=Match.Status.FINISHED, home_score=1, away_score=3,
        )
        r = self._get()
        self.assertEqual(len(r.context['h2h']), 1)
        self.assertEqual(r.context['h2h_menang'], 1)
        self.assertContains(r, '3&ndash;1')

    def test_tanpa_laga_mendatang_nggak_error(self):
        Match.objects.all().delete()
        r = self._get()
        self.assertIsNone(r.context['match'])


class HalamanSkuadTests(TestCase):
    """SQ-01 & SQ-02 di lapisan halaman.

    Yang dijaga: konflik yang belum diputuskan harus KELIHATAN sebagai
    'Bentrok' dan ditandai jangan dipakai untuk konten. Status yang diam-diam
    dipilihkan app justru kebalikan dari maksud kartu ini.
    """

    @classmethod
    def setUpTestData(cls):
        from players.models import DataSource, Player, PlayerAvailability

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        cls.amad = Player.objects.create(
            name='Amad Diallo', team=cls.mu, position='WNG', is_active=True
        )
        cls.bruno = Player.objects.create(
            name='Bruno Fernandes', team=cls.mu, position='CAM', is_active=True
        )
        PlayerAvailability.objects.create(
            player=cls.amad, source=DataSource.FPL,
            status=PlayerAvailability.Status.DOUBTFUL,
            note='Foot injury - 75% chance of playing', chance_pct=75,
            source_updated_at=timezone.now() - timedelta(hours=6),
        )
        PlayerAvailability.objects.create(
            player=cls.amad, source=DataSource.NEWS,
            status=PlayerAvailability.Status.OUT,
            note='Sky Sports: Amad Diallo ruled out for three weeks',
            source_updated_at=timezone.now() - timedelta(hours=2),
        )
        PlayerAvailability.objects.create(
            player=cls.bruno, source=DataSource.FPL,
            status=PlayerAvailability.Status.FIT,
        )

    def test_konflik_muncul_di_panel(self):
        r = self.client.get(reverse('dashboard:squad'))
        self.assertEqual(len(r.context['konflik']), 1)
        self.assertEqual(r.context['konflik'][0]['player'].name, 'Amad Diallo')
        self.assertContains(r, 'Konflik Sumber')
        self.assertContains(r, '6 jam lalu')

    def test_tiga_aturan_ditulis_di_ui(self):
        """Permintaan eksplisit spesifikasi: aturannya di UI, bukan cuma dokumen."""
        r = self.client.get(reverse('dashboard:squad'))
        self.assertContains(r, 'jangan dipakai untuk konten')
        self.assertContains(r, 'bukan data sumber')
        self.assertContains(r, 'satu jam sebelum kick-off')

    def test_belum_diputuskan_tertulis_bentrok(self):
        r = self.client.get(reverse('dashboard:squad'))
        baris = {b['player'].name: b for b in r.context['baris']}
        self.assertEqual(baris['Amad Diallo']['label'], 'Bentrok')
        self.assertFalse(baris['Amad Diallo']['aman_untuk_konten'])
        self.assertEqual(baris['Bruno Fernandes']['label'], 'Bugar')

    def test_analis_memutuskan_lalu_membatalkan(self):
        from players.models import AvailabilityDecision, DataSource

        r = self.client.post(
            reverse('dashboard:availability_decide', args=[self.amad.pk]),
            {'sumber': DataSource.FPL, 'catatan': 'Ikut latihan penuh'},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AvailabilityDecision.objects.filter(player=self.amad).exists())

        r = self.client.get(reverse('dashboard:squad'))
        baris = {b['player'].name: b for b in r.context['baris']}
        self.assertEqual(baris['Amad Diallo']['label'], 'Diragukan')
        self.assertEqual(baris['Amad Diallo']['hasil']['asal'], 'analis')
        self.assertEqual(len(r.context['konflik']), 0)

        self.client.post(reverse('dashboard:availability_reset', args=[self.amad.pk]))
        r = self.client.get(reverse('dashboard:squad'))
        self.assertEqual(len(r.context['konflik']), 1)

    def test_sumber_tanpa_status_ditolak(self):
        from players.models import DataSource

        r = self.client.post(
            reverse('dashboard:availability_decide', args=[self.amad.pk]),
            {'sumber': DataSource.HIGHLIGHTLY},
        )
        self.assertEqual(r.status_code, 400)

    def test_header_menyebut_jumlah_sumber(self):
        r = self.client.get(reverse('dashboard:squad'))
        self.assertEqual(len(r.context['sumber_terpakai']), 2)
        self.assertContains(r, 'sumber direkonsiliasi')


class HalamanPascaTests(TestCase):
    """Tahap 4 — kriteria selesai handoff: laporan satu laga lama bisa
    dihasilkan tanpa campur tangan manual."""

    @classmethod
    def setUpTestData(cls):
        from matches.models import MatchEvent, MatchTeamStatistics, PlayerMatchStatistics
        from players.models import Player

        cls.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        cls.lawan = Team.objects.create(name='Ipswich Town', short_name='Ipswich')

        # Delapan laga riwayat supaya PS-02 punya sebaran.
        for i in range(8):
            m = Match.objects.create(
                home_team=cls.mu, away_team=cls.lawan,
                kickoff_at=timezone.now() - timedelta(days=10 + i),
                season=2026, status=Match.Status.FINISHED, home_score=1, away_score=1,
            )
            MatchTeamStatistics.objects.create(
                match=m, team=cls.mu, shots_total=8 + (i % 5), possession_pct=52 + (i % 4)
            )
            MatchTeamStatistics.objects.create(match=m, team=cls.lawan, shots_total=9 + (i % 3))

        cls.match = Match.objects.create(
            home_team=cls.mu, away_team=cls.lawan,
            kickoff_at=timezone.now() - timedelta(days=1),
            season=2026, status=Match.Status.FINISHED, home_score=3, away_score=0,
            league_name='Premier League', venue='Old Trafford',
        )
        MatchTeamStatistics.objects.create(
            match=cls.match, team=cls.mu, shots_total=28, possession_pct=61, xg=3.2
        )
        MatchTeamStatistics.objects.create(match=cls.match, team=cls.lawan, shots_total=3)

        cls.bruno = Player.objects.create(name='Bruno Fernandes', team=cls.mu, position='CAM')
        PlayerMatchStatistics.objects.create(
            match=cls.match, player=cls.bruno, team=cls.mu, minutes_played=90,
            starter=True, goals=2, assists=1, key_passes=4, duels_won=6, duels_lost=2,
        )
        MatchEvent.objects.create(
            match=cls.match, team=cls.mu, player=cls.bruno,
            event_type=MatchEvent.EventType.GOAL, minute=23,
        )

    def test_halaman_hidup_dan_default_ke_laga_terbaru(self):
        r = self.client.get(reverse('dashboard:post_match'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['match'].pk, self.match.pk)
        self.assertContains(r, 'Pasca laga')

    def test_laporan_tersusun_tanpa_campur_tangan(self):
        r = self.client.get(reverse('dashboard:post_match'))
        laporan = r.context['laporan']
        self.assertTrue(laporan['paragraf'])
        self.assertIn('3–0', ' '.join(laporan['paragraf']))
        self.assertIn('Bruno Fernandes', ' '.join(laporan['paragraf']))

    def test_susun_ulang_mengubah_kalimat_bukan_angka(self):
        a = self.client.get(reverse('dashboard:post_match'), {'varian': 0})
        b = self.client.get(reverse('dashboard:post_match'), {'varian': 1})
        self.assertNotEqual(a.context['laporan']['judul'], b.context['laporan']['judul'])
        for r in (a, b):
            self.assertIn('3–0', ' '.join(r.context['laporan']['paragraf']))

    def test_angka_penentu_dan_nilai_pemain_terisi(self):
        r = self.client.get(reverse('dashboard:post_match'))
        self.assertTrue(r.context['angka'])
        self.assertLessEqual(len(r.context['angka']), 4)
        nilai = r.context['nilai_pemain']
        self.assertEqual(nilai[0]['player'].name, 'Bruno Fernandes')
        self.assertIsNotNone(nilai[0]['nilai'])

    def test_detektor_mengisi_saved_moments(self):
        from matches.models import SavedMoment

        self.client.get(reverse('dashboard:post_match'))
        momen = SavedMoment.objects.filter(match=self.match)
        self.assertTrue(momen.exists())
        self.assertTrue(all(m.origin == SavedMoment.Asal.SISTEM for m in momen))
        # Belum tercentang, jadi belum masuk prompt.
        self.assertFalse(any(m.selected for m in momen))

    def test_membuka_halaman_berkali_kali_tidak_menggandakan_momen(self):
        from matches.models import SavedMoment

        for _ in range(3):
            self.client.get(reverse('dashboard:post_match'))
        jumlah = SavedMoment.objects.filter(match=self.match).count()
        self.assertEqual(
            jumlah, SavedMoment.objects.filter(match=self.match).values('text').distinct().count()
        )

    def test_centang_momen_memasukkannya_ke_prompt(self):
        from matches.models import SavedMoment

        self.client.get(reverse('dashboard:post_match'))
        m = SavedMoment.objects.filter(match=self.match).first()
        self.client.post(reverse('dashboard:moment_toggle', args=[m.pk]))

        r = self.client.get(reverse('dashboard:post_match'), {'laga': self.match.pk})
        self.assertIn(m.text, r.context['prompt'])
        self.assertEqual(r.context['jumlah_terpilih'], 1)

    def test_analis_menambah_dan_menghapus_momen(self):
        from matches.models import SavedMoment

        self.client.post(
            reverse('dashboard:moment_add', args=[self.match.pk]),
            {'menit': 61, 'teks': 'Bentuk berubah jadi 4-2-2-2', 'angka': '61 menit'},
        )
        m = SavedMoment.objects.get(match=self.match, origin=SavedMoment.Asal.ANALIS)
        self.assertTrue(m.selected)

        r = self.client.get(reverse('dashboard:post_match'), {'laga': self.match.pk})
        self.assertIn('Bentuk berubah jadi 4-2-2-2', r.context['prompt'])

        self.client.post(reverse('dashboard:moment_delete', args=[m.pk]))
        self.assertFalse(SavedMoment.objects.filter(pk=m.pk).exists())

    def test_momen_tanpa_teks_ditolak(self):
        r = self.client.post(
            reverse('dashboard:moment_add', args=[self.match.pk]), {'teks': '   '}
        )
        self.assertEqual(r.status_code, 400)

    def test_tipe_konten_diganti_lewat_url(self):
        r = self.client.get(reverse('dashboard:post_match'), {'tipe': 'thread'})
        self.assertEqual(r.context['tipe'], 'thread')
        self.assertIn('thread di X', r.context['prompt'])

    def test_tipe_konten_ngawur_jatuh_ke_bawaan(self):
        r = self.client.get(reverse('dashboard:post_match'), {'tipe': '../../etc/passwd'})
        self.assertEqual(r.context['tipe'], 'carousel')

    def test_laga_lama_di_luar_chip_tetap_bisa_dibuka(self):
        lama = Match.objects.filter(status=Match.Status.FINISHED).order_by('kickoff_at').first()
        r = self.client.get(reverse('dashboard:post_match'), {'laga': lama.pk})
        self.assertEqual(r.context['match'].pk, lama.pk)

    def test_halaman_tetap_hidup_tanpa_laga_selesai(self):
        Match.objects.all().delete()
        r = self.client.get(reverse('dashboard:post_match'))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['match'])


class KomentarTemplateTests(TestCase):
    """Komentar `{# ... #}` tidak boleh melewati baris.

    Regex lexer Django dikompilasi tanpa DOTALL, jadi `{#` yang penutupnya ada
    di baris lain tidak pernah dikenali sebagai komentar — isinya tercetak apa
    adanya ke halaman. Bug ini sempat hidup di `base.html` tanpa ketahuan
    karena panelnya ada di bawah lipatan layar.
    """

    def test_tidak_ada_komentar_lintas_baris(self):
        import pathlib
        import re

        akar = pathlib.Path(__file__).resolve().parent / 'templates'
        salah = []
        for berkas in akar.rglob('*.html'):
            isi = berkas.read_text()
            for m in re.finditer(r'\{#.*?#\}', isi, re.S):
                if '\n' in m.group(0):
                    baris = isi[: m.start()].count('\n') + 1
                    salah.append(f'{berkas.name}:{baris}')
        self.assertEqual(
            salah, [], f'Pakai {{% comment %}} untuk komentar lintas baris: {salah}'
        )


class PilihHipotesisTests(TestCase):
    """PR-03 — analis memilih di halaman Pra-laga, bukan di Django admin.

    Handoff: *"App tidak menyimpulkan, dia menyiapkan bukti. Kesimpulan tetap
    dari analis."* Yang dijaga di sini bukan tombolnya, tapi tiga sifat yang
    kalau hilang bikin panel Cek Prediksi kehilangan gunanya.
    """

    def setUp(self):
        from datetime import timedelta

        from matches.models import HypothesisItem, PredictionSnapshot

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=timezone.now() + timedelta(days=3),
        )
        self.snapshot = PredictionSnapshot.objects.create(match=self.match)
        self.HypothesisItem = HypothesisItem
        self.items = [
            HypothesisItem.objects.create(
                snapshot=self.snapshot, order=i, text=f'Dugaan {i}',
                evidence_note=f'Dasar {i}',
            )
            for i in range(1, 6)
        ]

    def _pilih(self, item):
        return self.client.post(reverse('dashboard:hypothesis_toggle', args=[item.pk]))

    def test_memilih_dan_melepas(self):
        self._pilih(self.items[0])
        self.items[0].refresh_from_db()
        self.assertTrue(self.items[0].selected)

        self._pilih(self.items[0])
        self.items[0].refresh_from_db()
        self.assertFalse(self.items[0].selected)

    def test_maksimal_tiga_yang_dipertaruhkan(self):
        """Desain minta tiga kartu. Panel berisi enam dugaan bukan analisis."""
        from matches.lineup_prediction import MAKS_HIPOTESIS

        for item in self.items[:MAKS_HIPOTESIS]:
            self._pilih(item)

        r = self._pilih(self.items[MAKS_HIPOTESIS])
        self.items[MAKS_HIPOTESIS].refresh_from_db()
        self.assertFalse(self.items[MAKS_HIPOTESIS].selected)
        self.assertIn('penuh=1', r['Location'])

        self.assertEqual(
            self.snapshot.hypotheses.filter(selected=True).count(), MAKS_HIPOTESIS
        )

    def test_alasan_penolakan_kelihatan_di_halaman(self):
        """Ditolak diam-diam sama membingungkannya dengan tombol yang rusak."""
        from matches.lineup_prediction import MAKS_HIPOTESIS

        for item in self.items[:MAKS_HIPOTESIS]:
            self._pilih(item)
        r = self.client.get(
            reverse('dashboard:pre_match'), {'match': self.match.pk, 'penuh': '1'}
        )
        self.assertTrue(r.context['tolak_penuh'])
        self.assertContains(r, 'Lepas salah satu dulu')

    def test_sesudah_kickoff_pilihannya_beku(self):
        """Mengubah taruhan setelah tahu hasilnya menghapus guna panelnya."""
        from datetime import timedelta

        Match.objects.filter(pk=self.match.pk).update(
            kickoff_at=timezone.now() - timedelta(hours=1), status=Match.Status.LIVE
        )
        r = self._pilih(self.items[0])
        self.assertEqual(r.status_code, 400)
        self.items[0].refresh_from_db()
        self.assertFalse(self.items[0].selected)

    def test_kandidat_dan_taruhan_dipisah_di_halaman(self):
        self._pilih(self.items[0])
        r = self.client.get(reverse('dashboard:pre_match'), {'match': self.match.pk})
        self.assertEqual([h.text for h in r.context['hipotesis']], ['Dugaan 1'])
        self.assertEqual(len(r.context['kandidat']), 4)
        self.assertTrue(r.context['bisa_dipilih'])

    def test_snapshot_lama_tanpa_pilihan_tetap_tampil_utuh(self):
        """Kolom `selected` lahir belakangan. Snapshot lama nol pilihan —
        menampilkannya sebagai panel kosong bikin data yang ada kelihatan
        hilang."""
        from datetime import timedelta

        # Cap waktu snapshot HARUS ikut digeser. `created_at` itu auto_now_add,
        # jadi kalau cuma kickoff yang dimundurkan, snapshot-nya jadi
        # PASCA-peluit dan ditolak `prediction_before_kickoff()` — itu perilaku
        # yang dijaga, bukan bug.
        kickoff = timezone.now() - timedelta(hours=1)
        Match.objects.filter(pk=self.match.pk).update(
            kickoff_at=kickoff, status=Match.Status.LIVE
        )
        type(self.snapshot).objects.filter(pk=self.snapshot.pk).update(
            created_at=kickoff - timedelta(hours=5)
        )
        r = self.client.get(reverse('dashboard:pre_match'), {'match': self.match.pk})
        self.assertEqual(len(r.context['hipotesis']), 5)
        self.assertEqual(len(r.context['kandidat']), 0)
        self.assertFalse(r.context['bisa_dipilih'])


class PilihanIkutSnapshotBerikutnyaTests(TestCase):
    """Pilihan harus selamat waktu prediksi susunan diperbarui.

    Ini alasan `selected` jadi penanda, bukan penghapusan: `predict_lineup`
    bikin snapshot BARU tiap susunan berubah, dan snapshot baru lahir membawa
    seluruh kandidat lagi. Pilihan yang diwujudkan sebagai penghapusan hilang
    tiap kali prediksinya diperbarui, tanpa ada yang memberitahu.
    """

    def test_pilihan_terbawa_ke_snapshot_baru(self):
        from datetime import timedelta

        from matches.management.commands.predict_lineup import Command
        from matches.models import HypothesisItem, PredictionSnapshot

        mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        lawan = Team.objects.create(name='Ipswich Town')
        match = Match.objects.create(
            home_team=mu, away_team=lawan, kickoff_at=timezone.now() + timedelta(days=2)
        )
        lama = PredictionSnapshot.objects.create(match=match)
        HypothesisItem.objects.create(
            snapshot=lama, order=1, text='MU turun 4-2-3-1', selected=True
        )
        HypothesisItem.objects.create(
            snapshot=lama, order=2, text='Tembakan tepat >= 6', selected=False
        )

        kandidat = [
            {'text': 'MU turun 4-2-3-1', 'evidence_note': 'x'},
            {'text': 'Tembakan tepat >= 6', 'evidence_note': 'y'},
            {'text': 'Dugaan baru', 'evidence_note': 'z'},
        ]
        prediksi = {
            'slots': [], 'formation': '4-2-3-1', 'n_efektif': 5,
            'matches_used': [], 'warnings': [],
        }
        baru = Command._tulis(match, prediksi, 5, kandidat)

        hasil = {h.text: h.selected for h in baru.hypotheses.all()}
        self.assertTrue(hasil['MU turun 4-2-3-1'])
        self.assertFalse(hasil['Tembakan tepat >= 6'])
        self.assertFalse(hasil['Dugaan baru'])
