from django.test import SimpleTestCase, TestCase

from matches.management.commands.pull_fotmob import Command as PullFotMobCommand
from matches.management.commands.pull_squad_sdb import Command as PullSquadSdbCommand
from matches.management.commands.pull_squad import (
    MIN_SQUAD_FOR_DEACTIVATION,
    Command as PullSquadCommand,
)
from django.utils import timezone

from matches.models import Match, MatchExternalRef, MatchIngest
from players.models import DataSource, Player, Team


class SyncActiveFlagsTests(TestCase):
    """Penandaan aktif/non-aktif skuad.

    Bagian ini yang bikin 'Skuad Aktif' di produksi kebaca 294 padahal
    aslinya sekitar 58: `is_active` defaultnya True dan nggak ada satu pun
    command yang pernah nyetel jadi False, jadi mantan pemain numpuk terus.
    """

    def setUp(self):
        self.command = PullSquadCommand()
        self.team = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.other_team = Team.objects.create(name='Leeds United')

    def _make_squad(self, count, prefix='Pemain'):
        return [
            Player.objects.create(name=f'{prefix} {i}', team=self.team) for i in range(count)
        ]

    def test_pemain_di_luar_skuad_ditandai_non_aktif(self):
        squad = self._make_squad(MIN_SQUAD_FOR_DEACTIVATION)
        mantan = Player.objects.create(name='Mantan Pemain', team=self.team)

        self.command._sync_active_flags(self.team, {p.pk for p in squad})

        mantan.refresh_from_db()
        self.assertFalse(mantan.is_active)
        self.assertEqual(Player.objects.filter(team=self.team, is_active=True).count(), len(squad))

    def test_pemain_yang_balik_diaktifkan_lagi(self):
        """Dua arah, biar salah tanda bisa kekoreksi sendiri di run berikutnya."""
        squad = self._make_squad(MIN_SQUAD_FOR_DEACTIVATION)
        squad[0].is_active = False
        squad[0].save(update_fields=['is_active'])

        self.command._sync_active_flags(self.team, {p.pk for p in squad})

        squad[0].refresh_from_db()
        self.assertTrue(squad[0].is_active)

    def test_skuad_kekecilan_nggak_nandain_apa_apa(self):
        """Guard paling penting: respons kepotong (quota abis, error separuh
        jalan) nggak boleh ngosongin seluruh skuad."""
        squad = self._make_squad(MIN_SQUAD_FOR_DEACTIVATION)
        sebagian = squad[:3]

        self.command._sync_active_flags(self.team, {p.pk for p in sebagian})

        aktif = Player.objects.filter(team=self.team, is_active=True).count()
        self.assertEqual(aktif, len(squad), 'skuad nggak boleh kekosongan gara-gara respons parsial')

    def test_no_deactivate_nggak_ngubah_apa_apa(self):
        squad = self._make_squad(MIN_SQUAD_FOR_DEACTIVATION)
        mantan = Player.objects.create(name='Mantan Pemain', team=self.team)

        self.command._sync_active_flags(self.team, {p.pk for p in squad}, skip=True)

        mantan.refresh_from_db()
        self.assertTrue(mantan.is_active)

    def test_tim_lain_nggak_kesentuh(self):
        squad = self._make_squad(MIN_SQUAD_FOR_DEACTIVATION)
        pemain_lain = Player.objects.create(name='Pemain Leeds', team=self.other_team)

        self.command._sync_active_flags(self.team, {p.pk for p in squad})

        pemain_lain.refresh_from_db()
        self.assertTrue(pemain_lain.is_active)


class ParseHeightTests(SimpleTestCase):
    """Parser tinggi badan TheSportsDB.

    Versi lama nyatuin semua digit di string, jadi '179 cm (5 ft 10 in)'
    jadi 179510. SQLite nerima (nggak negakin batas kolom), Postgres nolak —
    ketauannya baru pas migrasi database.
    """

    def setUp(self):
        self.parse = PullSquadSdbCommand._parse_height_cm

    def test_format_meter(self):
        self.assertEqual(self.parse('1.83 m'), 183)
        self.assertEqual(self.parse('1,79 m'), 179)

    def test_format_sentimeter(self):
        self.assertEqual(self.parse('183 cm'), 183)

    def test_dua_satuan_sekaligus(self):
        """Regresi: ini yang dulu bikin 179510."""
        self.assertEqual(self.parse('179 cm (5 ft 10 in)'), 179)
        self.assertEqual(self.parse('1.79 m (5 ft 10 in)'), 179)

    def test_nilai_di_luar_nalar_ditolak(self):
        self.assertIsNone(self.parse('179510'))
        self.assertIsNone(self.parse('12 cm'))

    def test_input_kosong_atau_tanpa_angka(self):
        for value in ('', None, 'unknown'):
            self.assertIsNone(self.parse(value))


class FotMobCoerceTests(SimpleTestCase):
    """Pembacaan nilai statistik FotMob.

    FotMob campur tipe dalam satu payload: angka polos (13), string desimal
    ('0.79'), dan bentuk berpersentase ('415 (86%)'). Salah baca yang ketiga
    bikin akurasi umpan kesimpen sebagai 41586.
    """

    def setUp(self):
        self.coerce = PullFotMobCommand._coerce

    def test_angka_polos(self):
        self.assertEqual(self.coerce(13, 'shots_total'), 13)

    def test_string_desimal_ke_float(self):
        self.assertEqual(self.coerce('0.79', 'xg'), 0.79)

    def test_bentuk_berpersentase_ambil_angka_pertama(self):
        """Regresi: '415 (86%)' harus jadi 415, bukan 41586."""
        self.assertEqual(self.coerce('415 (86%)', 'passes_accurate'), 415)
        self.assertEqual(self.coerce('18 (49%)', 'long_balls_accurate'), 18)

    def test_field_integer_dibulatkan(self):
        self.assertEqual(self.coerce('7.6', 'touches'), 8)

    def test_field_float_nggak_dibulatkan(self):
        self.assertEqual(self.coerce('7.6', 'rating'), 7.6)

    def test_nilai_kosong_dan_nggak_valid(self):
        for value in (None, '', '-', 'n/a'):
            self.assertIsNone(self.coerce(value, 'touches'))

    def test_bentuk_dict_dengan_total(self):
        self.assertEqual(self.coerce({'total': 42}, 'touches'), 42)


class IncrementalIngestTests(TestCase):
    """Penyaring 'sudah pernah ditarik'.

    Laga yang selesai datanya final, tapi command dulu narik ulang semua tiap
    jalan. Buat 46 laga itu boros; buat 380 laga se-liga jadi ratusan
    panggilan per malam ke API yang nggak resmi tanpa dapat apa-apa.
    """

    def setUp(self):
        home = Team.objects.create(name='Manchester United', is_manchester_united=True)
        away = Team.objects.create(name='Brighton')
        self.match = Match.objects.create(
            home_team=home, away_team=away, kickoff_at=timezone.now()
        )
        MatchExternalRef.objects.create(
            match=self.match, source=DataSource.FOTMOB, external_id=4813745
        )

    def test_belum_ditarik_berarti_belum_pernah(self):
        self.assertFalse(PullFotMobCommand._already_ingested(4813745))

    def test_setelah_dicatat_dianggap_sudah(self):
        MatchIngest.objects.create(match=self.match, source=DataSource.FOTMOB, rows=42)
        self.assertTrue(PullFotMobCommand._already_ingested(4813745))

    def test_catatan_dari_sumber_lain_nggak_ngaruh(self):
        """Understat dan FotMob dilacak terpisah — satu ditarik nggak berarti
        yang lain ikut."""
        MatchIngest.objects.create(match=self.match, source=DataSource.UNDERSTAT, rows=10)
        self.assertFalse(PullFotMobCommand._already_ingested(4813745))

    def test_id_nggak_dikenal_atau_ngawur(self):
        for value in (999999, None, 'bukan-angka'):
            self.assertFalse(PullFotMobCommand._already_ingested(value))


class CurrentFootballSeasonTests(SimpleTestCase):
    """Musim Understat harus ikut tanggal, bukan konstanta.

    Regresi bug 4.9: `UNDERSTAT_DEFAULT_SEASON` dipatok '2025'. Begitu musim
    itu tamat, semua laganya sudah tertarik dan penyaring inkremental melewati
    semuanya — cron lapor "0 match dicocokkan" dengan exit code 0 tiap malam,
    dan musim berjalan nggak pernah dapat xG sama sekali.
    """

    def test_musim_baru_mulai_juli(self):
        from datetime import date

        from config.settings import _current_football_season

        # 30 Juni masih musim lama, 1 Juli sudah musim baru.
        self.assertEqual(_current_football_season(date(2026, 6, 30)), 2025)
        self.assertEqual(_current_football_season(date(2026, 7, 1)), 2026)

    def test_paruh_kedua_musim_pakai_tahun_pembuka(self):
        from datetime import date

        from config.settings import _current_football_season

        # Januari–Mei 2027 masih musim 2026/27.
        self.assertEqual(_current_football_season(date(2026, 12, 31)), 2026)
        self.assertEqual(_current_football_season(date(2027, 1, 5)), 2026)
        self.assertEqual(_current_football_season(date(2027, 5, 24)), 2026)

    def test_setelan_terbaca_sebagai_musim_berjalan(self):
        from datetime import date

        from django.conf import settings

        from config.settings import _current_football_season

        # Tanpa override env, nilainya harus musim berjalan — bukan angka mati.
        self.assertEqual(
            str(settings.UNDERSTAT_DEFAULT_SEASON),
            str(_current_football_season(date.today())),
        )


class PullInjuriesQuotaTests(TestCase):
    """Regresi: pull_injuries menghabiskan quota harian Highlightly tiap malam.

    Penyebabnya dia me-loop SEMUA Player bertim MU — di produksi 98 orang, 60
    di antaranya mantan pemain yang tidak akan pernah lolos verifikasi klub.
    Tiap mantan pemain membakar 1 panggilan pencarian + verifikasi kandidat,
    lalu gagal, tiap malam, selamanya.
    """

    def setUp(self):
        from players.models import Player, Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.aktif = [
            Player.objects.create(name=f'Aktif {i}', team=self.mu, is_active=True)
            for i in range(3)
        ]
        self.mantan = [
            Player.objects.create(name=f'Mantan {i}', team=self.mu, is_active=False)
            for i in range(4)
        ]

    def _jalankan(self, **opts):
        """Jalankan command dengan klien tiruan; kembalikan nama yang dipanggil."""
        from unittest.mock import patch

        from django.core.management import call_command

        dipanggil = []

        class KlienPalsu:
            def get_player(self, external_id):
                dipanggil.append(('detail', external_id))
                return {'profile': {'club': {'current': 'Manchester United FC'}}, 'injuries': []}

            def _get(self, path, params=None):
                dipanggil.append(('cari', (params or {}).get('name')))
                return {'data': []}

        with patch(
            'matches.management.commands.pull_injuries.HighlightlyClient',
            return_value=KlienPalsu(),
        ):
            call_command('pull_injuries', **opts)
        return dipanggil

    def test_mantan_pemain_nggak_ikut_dipanggil(self):
        dipanggil = self._jalankan()
        dicari = [nama for jenis, nama in dipanggil if jenis == 'cari']
        self.assertEqual(len(dicari), 3, 'cuma 3 pemain aktif yang boleh dipanggil')
        for nama in dicari:
            self.assertTrue(nama.startswith('Aktif'), f'{nama} mantan pemain, harusnya dilewati')

    def test_include_inactive_mengembalikan_perilaku_lama(self):
        dipanggil = self._jalankan(include_inactive=True)
        dicari = [nama for jenis, nama in dipanggil if jenis == 'cari']
        self.assertEqual(len(dicari), 7)

    def test_pemain_yang_sudah_ke_link_diproses_duluan(self):
        from players.models import DataSource, PlayerExternalRef

        # Yang ke-link cuma butuh 1 panggilan; harus didahulukan supaya kalau
        # quota habis di tengah, yang kepotong adalah pencarian pemain baru.
        PlayerExternalRef.objects.create(
            source=DataSource.HIGHLIGHTLY, external_id=99, player=self.aktif[2]
        )
        dipanggil = self._jalankan()
        self.assertEqual(dipanggil[0], ('detail', 99))

    def test_batas_panggilan_menghentikan_run_dengan_rapi(self):
        # Tiap pemain tak ter-link dianggarkan 1 + MAX_VERIFY_PER_PLAYER
        # panggilan, jadi anggaran segitu cuma cukup buat satu orang.
        from matches.management.commands.pull_injuries import MAX_VERIFY_PER_PLAYER

        dipanggil = self._jalankan(max_calls=1 + MAX_VERIFY_PER_PLAYER)
        dicari = [n for jenis, n in dipanggil if jenis == 'cari']
        self.assertEqual(len(dicari), 1, 'harus berhenti setelah anggaran habis')
