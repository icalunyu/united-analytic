from django.test import SimpleTestCase, TestCase

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


class TeamAliasTests(SimpleTestCase):
    """Julukan klub yang tidak bisa diturunkan dari nama resmi.

    Regresi: Highlightly menyebut klub itu 'Wolves', provider lain
    'Wolverhampton Wanderers'. Karena 'wolves' bukan awalan dari
    'wolverhampton wanderers', team_names_match gagal dan lahirlah dua record
    Team untuk satu klub — 6 laga nyangkut di klub tanpa satu pun pemain.
    """

    def test_julukan_dikenali(self):
        self.assertTrue(team_names_match('Wolves', 'Wolverhampton Wanderers'))
        self.assertTrue(team_names_match('Spurs', 'Tottenham Hotspur FC'))
        self.assertTrue(team_names_match('Man Utd', 'Manchester United FC'))
        self.assertTrue(team_names_match('West Brom', 'West Bromwich Albion'))

    def test_awalan_persis_tetap_jalan(self):
        # Jalur lama harus tetap hidup, bukan tergantikan peta alias.
        self.assertTrue(team_names_match('Brighton', 'Brighton & Hove Albion FC'))

    def test_klub_berbeda_tetap_dibedakan(self):
        # Peta alias tidak boleh bikin klub sekota tertukar.
        self.assertFalse(team_names_match('Manchester United', 'Manchester City'))
        self.assertFalse(team_names_match('Sheffield United', 'Sheffield Wednesday'))

    def test_sheffield_sengaja_nggak_masuk_peta(self):
        # 'Sheffield' ambigu (United atau Wednesday?), jadi tidak dialiaskan.
        #
        # Catatan jujur: nama telanjang 'Sheffield' TETAP cocok ke keduanya
        # lewat aturan awalan yang sudah ada sejak dulu — itu perilaku lama dan
        # di luar cakupan perbaikan ini. Yang dijaga di sini cuma satu: peta
        # alias tidak boleh ikut memperparah dengan memihak salah satu.
        from players.name_utils import normalize_team_name

        self.assertEqual(normalize_team_name('Sheffield'), 'sheffield')


class RosterLeftoverMergeTests(TestCase):
    """Aturan `_merge_roster_leftovers` di merge_duplicates.

    Sisa roster = record tanpa statistik dari `pull_match_events_pl`, kembar
    dengan record bermain-beneran di tim lain karena pemainnya pindah klub.
    """

    def setUp(self):
        from players.models import Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.leeds = Team.objects.create(name='Leeds United FC')
        self.chelsea = Team.objects.create(name='Chelsea FC')

    @staticmethod
    def _gabung():
        from django.core.management import call_command

        call_command('merge_duplicates', '--apply', '--players-only', verbosity=0)

    def _beri_statistik(self, player, team):
        from django.utils import timezone

        from matches.models import Match, PlayerMatchStatistics

        match = Match.objects.create(
            home_team=team, away_team=self.chelsea, kickoff_at=timezone.now()
        )
        PlayerMatchStatistics.objects.create(match=match, player=player, team=team)

    def test_sisa_roster_tanpa_statistik_digabung(self):
        from players.models import Player

        main = Player.objects.create(name='Aaron Cresswell', team=self.leeds)
        self._beri_statistik(main, self.leeds)
        sisa = Player.objects.create(name='Aaron Cresswell', team=self.chelsea)

        self._gabung()
        self.assertFalse(Player.objects.filter(pk=sisa.pk).exists())
        self.assertTrue(Player.objects.filter(pk=main.pk).exists())

    def test_record_mu_dipertahankan_walau_statistiknya_di_record_lain(self):
        """Kasus Karl Darlow.

        Statistiknya menempel di record Leeds, tapi dia terdaftar di skuad MU
        yang disegarkan tiap hari. Kalau kanoniknya dipilih semata-mata dari
        'siapa yang punya statistik', dia lenyap dari skuad MU.

        Record MU-nya harus didukung feed skuad — lihat KanonikBukanHantuTests
        untuk kenapa 'ada di MU' saja tidak cukup.
        """
        from players.models import DataSource, Player, PlayerExternalRef

        di_mu = Player.objects.create(name='Karl Darlow', team=self.mu)
        PlayerExternalRef.objects.create(
            player=di_mu, source=DataSource.FOOTBALL_DATA, external_id=7913
        )
        di_leeds = Player.objects.create(name='Karl Darlow', team=self.leeds)
        self._beri_statistik(di_leeds, self.leeds)

        self._gabung()
        tersisa = Player.objects.filter(name='Karl Darlow')
        self.assertEqual(tersisa.count(), 1)
        self.assertEqual(tersisa.first().pk, di_mu.pk)
        self.assertTrue(tersisa.first().team.is_manchester_united)
        # Statistiknya harus ikut pindah, bukan hilang bersama record Leeds.
        from matches.models import PlayerMatchStatistics

        self.assertEqual(PlayerMatchStatistics.objects.filter(player=di_mu).count(), 1)
        self.assertFalse(Player.objects.filter(pk=di_leeds.pk).exists())

    def test_provider_yang_menerbitkan_dua_id_memblokir_penggabungan(self):
        """Kasus Ben Johnson — dua orang berbeda yang kebetulan senama."""
        from players.models import DataSource, Player, PlayerExternalRef

        a = Player.objects.create(name='Ben Johnson', team=self.leeds)
        self._beri_statistik(a, self.leeds)
        b = Player.objects.create(name='Ben Johnson', team=self.chelsea)
        PlayerExternalRef.objects.create(player=a, source=DataSource.PREMIER_LEAGUE, external_id=1)
        PlayerExternalRef.objects.create(player=b, source=DataSource.PREMIER_LEAGUE, external_id=2)

        self._gabung()
        self.assertEqual(Player.objects.filter(name='Ben Johnson').count(), 2)

    def test_dua_duanya_punya_statistik_nggak_disentuh(self):
        from players.models import Player

        a = Player.objects.create(name='Danny Ward', team=self.leeds)
        b = Player.objects.create(name='Danny Ward', team=self.chelsea)
        self._beri_statistik(a, self.leeds)
        self._beri_statistik(b, self.chelsea)

        self._gabung()
        self.assertEqual(Player.objects.filter(name='Danny Ward').count(), 2)

    def test_nama_lengkap_beda_nggak_digabung(self):
        """Kunci grup cuma (inisial, nama belakang) — terlalu longgar lintas tim."""
        from players.models import Player

        adam = Player.objects.create(name='Adam Armstrong', team=self.leeds)
        self._beri_statistik(adam, self.leeds)
        Player.objects.create(name='Aaron Armstrong', team=self.chelsea)

        self._gabung()
        self.assertEqual(Player.objects.filter(name__endswith='Armstrong').count(), 2)


class KanonikBukanHantuTests(TestCase):
    """Record MU tidak otomatis menang — harus aktif dan bukan hantu komentar.

    Parser komentar ESPN sempat salah-atribusi pemain lawan ke MU, menyisakan
    record non-aktif, nol statistik, sumber `espn_commentary` saja. Ademola
    Lookman dan Daniel James punya record MU semacam itu padahal tidak pernah
    membela MU.
    """

    def setUp(self):
        from players.models import Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.villa = Team.objects.create(name='Aston Villa FC')
        self.lawan = Team.objects.create(name='Chelsea FC')

    def _beri_statistik(self, player, team):
        from django.utils import timezone

        from matches.models import Match, PlayerMatchStatistics

        match = Match.objects.create(
            home_team=team, away_team=self.lawan, kickoff_at=timezone.now()
        )
        PlayerMatchStatistics.objects.create(match=match, player=player, team=team)

    @staticmethod
    def _gabung():
        from django.core.management import call_command

        call_command('merge_duplicates', '--apply', '--players-only', verbosity=0)

    def test_record_hantu_komentar_nggak_boleh_jadi_kanonik(self):
        from players.models import DataSource, Player, PlayerExternalRef

        hantu = Player.objects.create(name='Ademola Lookman', team=self.mu, is_active=False)
        PlayerExternalRef.objects.create(
            player=hantu, source=DataSource.ESPN_COMMENTARY, external_id=1926081934
        )
        asli = Player.objects.create(name='Ademola Lookman', team=self.villa)
        PlayerExternalRef.objects.create(player=asli, source=DataSource.FOTMOB, external_id=690516)
        self._beri_statistik(asli, self.villa)

        self._gabung()
        tersisa = Player.objects.filter(name='Ademola Lookman')
        self.assertEqual(tersisa.count(), 1)
        self.assertEqual(tersisa.first().pk, asli.pk)
        self.assertFalse(tersisa.first().team.is_manchester_united)

    def test_mantan_pemain_mu_kalah_dari_klub_barunya(self):
        """Jadon Sancho: record MU-nya non-aktif karena sudah pindah."""
        from players.models import DataSource, Player, PlayerExternalRef

        lama = Player.objects.create(name='Jadon Sancho', team=self.mu, is_active=False)
        PlayerExternalRef.objects.create(
            player=lama, source=DataSource.PREMIER_LEAGUE, external_id=14801
        )
        baru = Player.objects.create(name='Jadon Sancho', team=self.villa)
        PlayerExternalRef.objects.create(player=baru, source=DataSource.FOTMOB, external_id=846381)
        self._beri_statistik(baru, self.villa)

        self._gabung()
        tersisa = Player.objects.filter(name='Jadon Sancho')
        self.assertEqual(tersisa.count(), 1)
        self.assertEqual(tersisa.first().pk, baru.pk)

    def test_pemain_skuad_mu_aktif_tetap_menang(self):
        """Karl Darlow: aktif di skuad MU, sumbernya feed skuad, bukan komentar."""
        from players.models import DataSource, Player, PlayerExternalRef

        di_mu = Player.objects.create(name='Karl Darlow', team=self.mu, is_active=True)
        PlayerExternalRef.objects.create(
            player=di_mu, source=DataSource.FOOTBALL_DATA, external_id=7913
        )
        lama = Player.objects.create(name='Karl Darlow', team=self.villa)
        PlayerExternalRef.objects.create(player=lama, source=DataSource.FOTMOB, external_id=163604)
        self._beri_statistik(lama, self.villa)

        self._gabung()
        tersisa = Player.objects.filter(name='Karl Darlow')
        self.assertEqual(tersisa.count(), 1)
        self.assertEqual(tersisa.first().pk, di_mu.pk)
        self.assertTrue(tersisa.first().team.is_manchester_united)


class TransferMergeTests(TestCase):
    """Aturan `_merge_transfers`: statistik satu orang terbelah karena pindah klub.

    Bedanya dari sisa roster: di sini DUA-DUANYA punya statistik, jadi butuh
    bukti lebih kuat — tidak boleh ada satu tanggal pun yang muncul di dua
    record, karena satu orang tidak bisa membela dua klub di hari yang sama.
    """

    def setUp(self):
        from players.models import Team

        self.west_ham = Team.objects.create(name='West Ham United')
        self.burnley = Team.objects.create(name='Burnley')
        self.lawan = Team.objects.create(name='Chelsea FC')

    def _main(self, player, team, tanggal):
        from datetime import datetime, time, timezone as dt_tz

        from matches.models import Match, PlayerMatchStatistics

        kickoff = datetime.combine(tanggal, time(15, 0), tzinfo=dt_tz.utc)
        match = Match.objects.create(
            home_team=team, away_team=self.lawan, kickoff_at=kickoff
        )
        PlayerMatchStatistics.objects.create(match=match, player=player, team=team)

    @staticmethod
    def _gabung():
        from django.core.management import call_command

        call_command('merge_duplicates', '--apply', '--players-only', verbosity=0)

    def test_tanggal_terpisah_digabung_ke_klub_terakhir(self):
        from datetime import date

        from players.models import Player
        from matches.models import PlayerMatchStatistics

        lama = Player.objects.create(name='James Ward-Prowse', team=self.west_ham)
        baru = Player.objects.create(name='James Ward-Prowse', team=self.burnley)
        self._main(lama, self.west_ham, date(2025, 5, 11))
        self._main(baru, self.burnley, date(2026, 5, 24))

        self._gabung()
        tersisa = Player.objects.filter(name='James Ward-Prowse')
        self.assertEqual(tersisa.count(), 1)
        # Klub dengan penampilan terakhir yang menang.
        self.assertEqual(tersisa.first().pk, baru.pk)
        # Dan statistiknya menyatu, bukan hilang sebelah.
        self.assertEqual(PlayerMatchStatistics.objects.filter(player=baru).count(), 2)

    def test_main_di_hari_yang_sama_berarti_dua_orang(self):
        from datetime import date

        from players.models import Player

        a = Player.objects.create(name='Danny Ward', team=self.west_ham)
        b = Player.objects.create(name='Danny Ward', team=self.burnley)
        hari = date(2026, 3, 14)
        self._main(a, self.west_ham, hari)
        self._main(b, self.burnley, hari)

        self._gabung()
        self.assertEqual(Player.objects.filter(name='Danny Ward').count(), 2)

    def test_provider_yang_membedakan_tetap_memblokir(self):
        from datetime import date

        from players.models import DataSource, Player, PlayerExternalRef

        a = Player.objects.create(name='Josh King', team=self.west_ham)
        b = Player.objects.create(name='Josh King', team=self.burnley)
        self._main(a, self.west_ham, date(2025, 5, 11))
        self._main(b, self.burnley, date(2026, 5, 24))
        PlayerExternalRef.objects.create(player=a, source=DataSource.PREMIER_LEAGUE, external_id=3926)
        PlayerExternalRef.objects.create(player=b, source=DataSource.PREMIER_LEAGUE, external_id=128976)

        self._gabung()
        self.assertEqual(Player.objects.filter(name='Josh King').count(), 2)


class UnderstatAliasMergeTests(TestCase):
    """Aturan `_merge_understat_aliases` di merge_duplicates.

    Understat menulis nama lengkap, provider lain nama panggung. Kunci
    (inisial, nama belakang) membaca 'Amad Diallo Traore' dan 'Amad Diallo'
    sebagai dua orang — di produksi 146 laga vs 32 laga, satu orang.
    """

    def setUp(self):
        from players.models import Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.forest = Team.objects.create(name='Nottingham Forest FC')
        self.lawan = Team.objects.create(name='Chelsea FC')

    def _main(self, player, team, match=None):
        from django.utils import timezone

        from matches.models import Match, PlayerMatchStatistics

        match = match or Match.objects.create(
            home_team=team, away_team=self.lawan, kickoff_at=timezone.now()
        )
        PlayerMatchStatistics.objects.create(match=match, player=player, team=team)
        return match

    @staticmethod
    def _understat(player, external_id):
        from players.models import DataSource, PlayerExternalRef

        PlayerExternalRef.objects.create(
            player=player, source=DataSource.UNDERSTAT, external_id=external_id
        )

    @staticmethod
    def _gabung():
        from django.core.management import call_command

        call_command('merge_duplicates', '--apply', '--players-only', verbosity=0)

    def test_nama_panjang_understat_dilebur_ke_record_utama(self):
        from players.models import DataSource, Player, PlayerExternalRef
        from matches.models import PlayerMatchStatistics

        utama = Player.objects.create(name='Amad Diallo', team=self.mu)
        PlayerExternalRef.objects.create(player=utama, source=DataSource.ESPN, external_id=1)
        alias = Player.objects.create(name='Amad Diallo Traore', team=self.mu)
        self._understat(alias, 6885)

        laga = self._main(utama, self.mu)
        self._main(alias, self.mu, match=laga)  # bertumpuk di laga yang sama

        self._gabung()
        self.assertFalse(Player.objects.filter(pk=alias.pk).exists())
        self.assertTrue(Player.objects.filter(pk=utama.pk).exists())
        # Baris statistiknya menyatu, bukan salah satunya lenyap.
        self.assertEqual(PlayerMatchStatistics.objects.filter(player=utama).count(), 1)

    def test_dua_kandidat_ditolak(self):
        """Forest punya 'Jair Cunha' DAN 'Jair Paula' — 'Jair' tidak boleh memilih."""
        from players.models import DataSource, Player, PlayerExternalRef

        a = Player.objects.create(name='Jair Cunha', team=self.forest)
        b = Player.objects.create(name='Jair Paula', team=self.forest)
        for p, i in ((a, 11), (b, 12)):
            PlayerExternalRef.objects.create(player=p, source=DataSource.ESPN, external_id=i)
        alias = Player.objects.create(name='Jair Silva', team=self.forest)
        self._understat(alias, 7001)
        laga = self._main(a, self.forest)
        self._main(alias, self.forest, match=laga)

        self._gabung()
        self.assertTrue(Player.objects.filter(pk=alias.pk).exists())

    def test_tanpa_laga_bertumpuk_tidak_digabung(self):
        """Nama mirip saja tidak cukup — harus ada bukti pemecahannya nyata."""
        from players.models import DataSource, Player, PlayerExternalRef

        utama = Player.objects.create(name='Destiny Udogie', team=self.mu)
        PlayerExternalRef.objects.create(player=utama, source=DataSource.ESPN, external_id=21)
        alias = Player.objects.create(name='Iyenoma Destiny Udogie', team=self.mu)
        self._understat(alias, 7005)
        self._main(utama, self.mu)
        self._main(alias, self.mu)  # laga BERBEDA

        self._gabung()
        self.assertTrue(Player.objects.filter(pk=alias.pk).exists())

    def test_record_yang_dikenal_provider_lain_tidak_disentuh(self):
        from players.models import DataSource, Player, PlayerExternalRef

        utama = Player.objects.create(name='Ezri Konsa', team=self.mu)
        PlayerExternalRef.objects.create(player=utama, source=DataSource.ESPN, external_id=31)
        lain = Player.objects.create(name='Ezri Konsa Ngoyo', team=self.mu)
        self._understat(lain, 7006)
        PlayerExternalRef.objects.create(player=lain, source=DataSource.FOTMOB, external_id=99)
        laga = self._main(utama, self.mu)
        self._main(lain, self.mu, match=laga)

        self._gabung()
        self.assertTrue(Player.objects.filter(pk=lain.pk).exists())
