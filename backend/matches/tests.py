from django.test import SimpleTestCase, TestCase

from matches.management.commands.pull_fotmob import Command as PullFotMobCommand
from matches.management.commands.pull_squad_sdb import Command as PullSquadSdbCommand
from matches.management.commands.pull_squad import (
    MIN_SQUAD_FOR_DEACTIVATION,
    Command as PullSquadCommand,
)
from players.models import Player, Team


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
