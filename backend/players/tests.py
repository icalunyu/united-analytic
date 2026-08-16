from django.test import SimpleTestCase

from .name_utils import (
    fold_accents,
    normalize_team_name,
    player_identity_key,
    player_names_match,
    team_names_match,
)


class FoldAccentsTests(SimpleTestCase):
    def test_copot_aksen_yang_bisa_dipecah_nfkd(self):
        self.assertEqual(fold_accents('Šeško'), 'sesko')
        self.assertEqual(fold_accents('André Onana'), 'andre onana')
        self.assertEqual(fold_accents('Vítek'), 'vitek')

    def test_huruf_yang_nfkd_nggak_bisa_pecah(self):
        # Ini yang bikin bug awal: 'ı' Turki nggak punya dekomposisi NFKD,
        # jadi harus dipetakan manual.
        self.assertEqual(fold_accents('Bayındır'), 'bayindir')
        self.assertEqual(fold_accents('Ødegaard'), 'odegaard')
        self.assertEqual(fold_accents('Łukasz'), 'lukasz')

    def test_input_kosong(self):
        self.assertEqual(fold_accents(''), '')
        self.assertEqual(fold_accents(None), '')


class PlayerNameMatchTests(SimpleTestCase):
    def test_ejaan_beraksen_vs_polos_dianggap_orang_yang_sama(self):
        """Regresi: Highlightly nulis beraksen, provider lain nggak — dulu ini
        bikin row Player duplikat dan skuad MU menggelembung."""
        self.assertTrue(player_names_match('Benjamin Sesko', 'Benjamin Šeško'))
        self.assertTrue(player_names_match('Altay Bayindir', 'Altay Bayındır'))
        self.assertTrue(player_names_match('Radek Vitek', 'Radek Vítek'))

    def test_nama_singkat_vs_nama_lengkap(self):
        self.assertTrue(player_names_match('S. Amrabat', 'Sofyan Amrabat'))
        self.assertTrue(player_names_match('L. Shaw', 'Luke Shaw'))

    def test_inisial_beda_tetep_dianggap_orang_beda(self):
        self.assertFalse(player_names_match('T. Fletcher', 'J. Fletcher'))

    def test_nama_belakang_beda_tetep_dianggap_orang_beda(self):
        self.assertFalse(player_names_match('Bruno Fernandes', 'Bruno Guimaraes'))

    def test_mononym_fallback_ke_nama_belakang(self):
        self.assertTrue(player_names_match('Antony', 'Antony'))

    def test_identity_key_udah_difold(self):
        self.assertEqual(player_identity_key('Benjamin Šeško'), ('b', 'sesko'))
        self.assertEqual(player_identity_key(''), ('', ''))

    def test_nama_belakang_majemuk_masih_belum_ketangkep(self):
        """Sengaja didokumentasiin sebagai batasan yang diketahui, bukan
        dianggap benar: 'Amad Diallo' vs 'Amad Diallo Traore' masih dianggap
        2 orang karena nama belakang diambil dari kata terakhir doang."""
        self.assertFalse(player_names_match('Amad Diallo', 'Amad Diallo Traore'))


class TeamNameMatchTests(SimpleTestCase):
    def test_aksen_nggak_lagi_ngancurin_nama(self):
        """Regresi: _NON_ALNUM_PATTERN ganti karakter beraksen jadi SPASI,
        jadi 'Beşiktaş' dulu jadi 'be ikta' — namanya kepecah, bukan cuma
        beda ejaan."""
        self.assertEqual(normalize_team_name('Beşiktaş'), 'besiktas')
        self.assertEqual(normalize_team_name('Atlético Madrid'), 'atletico madrid')
        self.assertTrue(team_names_match('Atletico Madrid', 'Atlético Madrid'))
        self.assertTrue(team_names_match('Malmo FF', 'Malmö FF'))

    def test_suffix_klub_diabaikan(self):
        self.assertTrue(team_names_match('Manchester United', 'Manchester United FC'))
        self.assertTrue(team_names_match('Brighton', 'Brighton & Hove Albion FC'))

    def test_tim_sekota_tetep_dibedain(self):
        """Yang bikin aturan prefix ini nggak boleh terlalu longgar."""
        self.assertFalse(team_names_match('Manchester United', 'Manchester City'))

    def test_nama_kosong_nggak_cocok_sama_apa_pun(self):
        self.assertFalse(team_names_match('', 'Manchester United'))
