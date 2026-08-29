import re

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


class PredictionSnapshotTests(TestCase):
    """Fondasi panel Cek Prediksi — pembeda utama produk menurut handoff.

    Yang diuji di sini bukan CRUD, tapi dua hal yang kalau rusak merusaknya
    tanpa gejala: cap waktu yang ditulis ulang, dan penyaringan pra-kickoff.
    """

    def setUp(self):
        from datetime import datetime, timezone as dt_tz

        from players.models import Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.ipswich = Team.objects.create(name='Ipswich Town FC')
        self.kickoff = datetime(2026, 8, 30, 15, 30, tzinfo=dt_tz.utc)
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.ipswich, kickoff_at=self.kickoff
        )

    def _snapshot_pada(self, saat, note=''):
        """Bikin snapshot lalu paksa created_at-nya.

        auto_now_add mengabaikan nilai yang dikirim waktu create, jadi satu-
        satunya cara mengatur waktu di test adalah lewat queryset.update().
        """
        from matches.models import PredictionSnapshot

        snap = PredictionSnapshot.objects.create(match=self.match, note=note)
        PredictionSnapshot.objects.filter(pk=snap.pk).update(created_at=saat)
        snap.refresh_from_db()
        return snap

    def test_cap_waktu_tidak_ditulis_ulang_saat_disimpan_lagi(self):
        """REGRESI: kalau auto_now_add jadi auto_now, tabel ini kehilangan gunanya.

        Model lain di file yang sama memakai auto_now (MatchIngest.ingested_at,
        RawPayload.fetched_at, FieldConflict.detected_at), jadi keliru menyalin
        polanya itu sangat mungkin. Efeknya: prediksi yang dibuat sebelum laga
        mendadak bercap sesudah laga, dan Cek Prediksi diam-diam kosong.
        """
        from datetime import timedelta

        awal = self.kickoff - timedelta(days=2)
        snap = self._snapshot_pada(awal)

        snap.note = 'diedit setelah dibuat'
        snap.save()
        snap.refresh_from_db()

        self.assertEqual(snap.created_at, awal, 'created_at tidak boleh berubah saat save ulang')
        self.assertTrue(snap.before_kickoff)

    def test_ambil_versi_terakhir_sebelum_kickoff(self):
        from datetime import timedelta

        self._snapshot_pada(self.kickoff - timedelta(days=3), 'versi awal')
        terbaru = self._snapshot_pada(self.kickoff - timedelta(hours=2), 'versi final')

        dipakai = self.match.prediction_before_kickoff()
        self.assertIsNotNone(dipakai)
        self.assertEqual(dipakai.pk, terbaru.pk)
        self.assertEqual(dipakai.note, 'versi final')

    def test_versi_sesudah_peluit_tidak_bisa_menyamar(self):
        """Inti klaim produknya: analisis dibuat sebelum laga, bukan sesudah fakta.

        Handoff melarang mekanisme kunci, jadi yang menjaga bukan lock melainkan
        penyaring waktu di query.
        """
        from datetime import timedelta

        sah = self._snapshot_pada(self.kickoff - timedelta(hours=1), 'sah')
        curang = self._snapshot_pada(self.kickoff + timedelta(hours=1), 'ditulis pas jeda')

        dipakai = self.match.prediction_before_kickoff()
        self.assertEqual(dipakai.pk, sah.pk)
        self.assertNotEqual(dipakai.pk, curang.pk)
        self.assertFalse(curang.before_kickoff)

    def test_tanpa_prediksi_pra_laga_mengembalikan_none(self):
        from datetime import timedelta

        self._snapshot_pada(self.kickoff + timedelta(minutes=5))
        self.assertIsNone(self.match.prediction_before_kickoff())

    def test_snapshot_menyimpan_hipotesis_dan_susunan(self):
        from datetime import timedelta

        from matches.models import HypothesisItem, LineupSlot
        from players.models import Player

        snap = self._snapshot_pada(self.kickoff - timedelta(hours=3))
        HypothesisItem.objects.create(
            snapshot=snap, order=1,
            text='MU bikin peluang utama dari sisi kiri',
            evidence_note='lebih dari separuh tembakan berawal dari sepertiga kiri',
        )
        pemain = Player.objects.create(name='Bruno Fernandes', team=self.mu)
        LineupSlot.objects.create(
            snapshot=snap, slot=10, position=LineupSlot.Position.AM,
            player=pemain, confidence_pct=80, is_key=True,
        )

        dipakai = self.match.prediction_before_kickoff()
        self.assertEqual(dipakai.hypotheses.count(), 1)
        self.assertEqual(dipakai.hypotheses.first().outcome, HypothesisItem.Outcome.PENDING)
        self.assertEqual(dipakai.lineup_slots.first().player, pemain)

    def test_slot_tidak_boleh_dobel_dalam_satu_snapshot(self):
        from datetime import timedelta

        from django.db import IntegrityError

        from matches.models import LineupSlot

        snap = self._snapshot_pada(self.kickoff - timedelta(hours=3))
        LineupSlot.objects.create(snapshot=snap, slot=1, position=LineupSlot.Position.GK)
        with self.assertRaises(IntegrityError):
            LineupSlot.objects.create(snapshot=snap, slot=1, position=LineupSlot.Position.CB)

    def test_jeda_ke_kickoff_negatif_kalau_dibuat_sesudah_peluit(self):
        from datetime import timedelta

        snap = self._snapshot_pada(self.kickoff + timedelta(hours=2))
        self.assertLess(snap.lead_time.total_seconds(), 0)


class NormalisasiKoordinatTests(SimpleTestCase):
    """ESPN mengirim dua format koordinat, dan bedanya bukan cuma skala.

    Format lama: 0..1, dengan 0 = di garis gawang yang diserang.
    Format baru (musim 2026): 0..100, dengan 100 = di gawang.

    Membagi 100 saja membuat gol dibaca sebagai kejadian paling tidak
    berbahaya. Dan karena `_danger` menjepit hasilnya ke [0,1], salah format
    tidak pernah memunculkan error — kurvanya cuma diam-diam salah.
    """

    @staticmethod
    def _plays(pasangan):
        from matches.models import MatchPlay

        return [MatchPlay(play_type=t, field_x=x, field_y=x) for t, x in pasangan]

    def _normalkan(self, plays):
        from matches.management.commands.pull_match_events_espn import Command

        Command._normalize_positions(plays)
        return plays

    def test_format_baru_dibalik_bukan_cuma_dibagi(self):
        plays = self._plays([('goal', 97.5), ('foul', 51.3)])
        self._normalkan(plays)
        # Gol di 97.5 artinya nyaris di gawang -> harus jadi mendekati 0.
        self.assertAlmostEqual(plays[0].field_x, 0.025, places=3)
        self.assertAlmostEqual(plays[1].field_x, 0.487, places=3)

    def test_gol_format_baru_menghasilkan_bahaya_tinggi(self):
        """Uji yang sebenarnya: hasil akhirnya masuk akal, bukan cuma angkanya."""
        from matches.momentum import _danger

        plays = self._plays([('goal', 97.5)])
        sebelum = _danger(plays[0])
        self._normalkan(plays)
        sesudah = _danger(plays[0])
        self.assertAlmostEqual(sebelum, 0.4, places=2)  # dijepit ke minimum
        self.assertGreater(sesudah, 0.9, 'gol harus mendekati bahaya maksimum')

    def test_format_lama_tidak_disentuh(self):
        plays = self._plays([('goal', 0.22), ('foul', 0.63)])
        self._normalkan(plays)
        self.assertAlmostEqual(plays[0].field_x, 0.22)
        self.assertAlmostEqual(plays[1].field_x, 0.63)

    def test_deteksi_per_laga_bukan_per_nilai(self):
        """Nilai 0..100 yang kebetulan kecil ikut dikonversi karena satu laga
        tidak pernah mencampur dua format."""
        plays = self._plays([('shot-on-target', 0.8), ('goal', 96.0)])
        self._normalkan(plays)
        # 0.8 dalam laga format baru artinya nyaris di gawang SENDIRI.
        self.assertAlmostEqual(plays[0].field_x, 0.992, places=3)
        self.assertAlmostEqual(plays[1].field_x, 0.04, places=3)

    def test_koordinat_kosong_tetap_kosong(self):
        from matches.models import MatchPlay

        plays = [MatchPlay(play_type='goal', field_x=None, field_y=None),
                 MatchPlay(play_type='foul', field_x=88.0, field_y=None)]
        self._normalkan(plays)
        self.assertIsNone(plays[0].field_x)
        self.assertIsNone(plays[1].field_y)
        self.assertAlmostEqual(plays[1].field_x, 0.12, places=3)


class UnderstatResolusiPemainTests(TestCase):
    """Understat menulis nama lengkap, provider lain nama panggung.

    Regresi: 'Amad Diallo Traore' (Understat) vs 'Amad Diallo' (ESPN/FotMob)
    dibaca sebagai dua orang karena kunci pencocokan cuma (inisial, nama
    belakang) — 'diallo' vs 'traore'. Akibatnya 146 laga di satu record dan 32
    di record lain: statistik satu orang terbelah tanpa gejala.
    """

    def setUp(self):
        from players.models import Player, Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.forest = Team.objects.create(name='Nottingham Forest FC')
        self.amad = Player.objects.create(name='Amad Diallo', team=self.mu)

    @staticmethod
    def _resolve(external_id, name, team):
        from matches.management.commands.pull_xg_understat import Command

        return Command._resolve_player(external_id, name, team)

    def test_nama_lebih_panjang_menempel_ke_record_yang_ada(self):
        hasil = self._resolve(6885, 'Amad Diallo Traore', self.mu)
        self.assertEqual(hasil.pk, self.amad.pk, 'harus nempel, bukan bikin record baru')

        from players.models import Player

        self.assertEqual(Player.objects.filter(team=self.mu).count(), 1)

    def test_ref_understat_ikut_dibuat_supaya_penarikan_berikutnya_langsung_ketemu(self):
        from players.models import DataSource, PlayerExternalRef

        self._resolve(6885, 'Amad Diallo Traore', self.mu)
        self.assertTrue(
            PlayerExternalRef.objects.filter(
                source=DataSource.UNDERSTAT, external_id=6885, player=self.amad
            ).exists()
        )

    def test_dua_kandidat_TIDAK_dipaksa_menempel(self):
        """Kasus nyata: Forest punya 'Jair Cunha' DAN 'Jair Paula'."""
        from players.models import Player

        Player.objects.create(name='Jair Cunha', team=self.forest)
        Player.objects.create(name='Jair Paula', team=self.forest)

        hasil = self._resolve(7001, 'Jair', self.forest)
        self.assertEqual(Player.objects.filter(team=self.forest).count(), 3)
        self.assertNotIn(hasil.name, ('Jair Cunha', 'Jair Paula'))

    def test_entitas_html_diurai(self):
        from players.models import Player, Team

        everton = Team.objects.create(name='Everton FC')
        asli = Player.objects.create(name="Jake O'Brien", team=everton)

        hasil = self._resolve(7002, 'Jake O&#039;Brien', everton)
        self.assertEqual(hasil.pk, asli.pk)
        self.assertEqual(Player.objects.filter(team=everton).count(), 1)

    def test_tanda_hubung_disamakan_dengan_spasi(self):
        from players.models import Player, Team

        fulham = Team.objects.create(name='Fulham FC')
        asli = Player.objects.create(name='Emile Smith Rowe', team=fulham)

        hasil = self._resolve(7003, 'Emile Smith-Rowe', fulham)
        self.assertEqual(hasil.pk, asli.pk)

    def test_nama_satu_kata_tidak_dijadikan_bukti(self):
        from players.models import Player, Team

        city = Team.objects.create(name='Manchester City FC')
        Player.objects.create(name='Savio Moreira', team=city)

        hasil = self._resolve(7004, 'Savio', city)
        self.assertNotEqual(hasil.name, 'Savio Moreira')
        self.assertEqual(Player.objects.filter(team=city).count(), 2)


class UnderstatShotSourceTests(TestCase):
    """_save_shots dulu menghapus SELURUH tembakan laga, termasuk milik FotMob."""

    def setUp(self):
        from django.utils import timezone

        from players.models import Team

        self.mu = Team.objects.create(name='Manchester United FC', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Chelsea FC')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now()
        )

    def test_hanya_tembakan_understat_yang_dihapus(self):
        from matches.management.commands.pull_xg_understat import Command
        from matches.models import MatchShot
        from players.models import DataSource

        MatchShot.objects.create(
            match=self.match, team=self.mu, source=DataSource.FOTMOB,
            external_id='fm-1', minute=10, xg=0.3,
        )
        MatchShot.objects.create(
            match=self.match, team=self.mu, source=DataSource.UNDERSTAT,
            external_id='us-lama', minute=20, xg=0.2,
        )

        Command()._save_shots(self.match, {})

        sisa = MatchShot.objects.filter(match=self.match)
        self.assertEqual(sisa.count(), 1)
        self.assertEqual(sisa.first().source, DataSource.FOTMOB)

    def test_tembakan_baru_membawa_sumbernya(self):
        from matches.management.commands.pull_xg_understat import Command
        from matches.models import MatchShot
        from players.models import DataSource

        Command()._save_shots(self.match, {'h': [{
            'id': '99', 'minute': '33', 'xG': '0.44', 'result': 'Goal',
            'X': '0.9', 'Y': '0.5', 'player_id': None, 'player': None,
        }]})
        shot = MatchShot.objects.get(match=self.match, external_id='99')
        self.assertEqual(shot.source, DataSource.UNDERSTAT)


class NolPalsuStatistikTimTests(SimpleTestCase):
    """ESPN mengirim blok statistik penuh berisi '0' saat datanya tidak ada.

    Karena non-null, angka itu lolos semua penyaring dan ikut rata-rata:
    penguasaan bola MU musim 2022 terbaca 49,4% padahal 56,4% — selisih 7 poin
    dari 8 laga, cukup untuk mengarang tren yang tidak pernah terjadi.
    """

    @staticmethod
    def _buang(values):
        from matches.management.commands.pull_match_events_espn import Command

        return Command._buang_nol_palsu(values)

    def test_blok_nol_seluruhnya_jadi_none(self):
        hasil = self._buang({'possession_pct': 0, 'passes_total': 0, 'shots_total': 0,
                             'corners': 0, 'fouls': 0})
        self.assertTrue(all(v is None for v in hasil.values()))

    def test_nol_tembakan_yang_SAH_tidak_ikut_dibuang(self):
        """Tim bisa benar-benar nol tembakan. Yang mustahil itu nol penguasaan
        bola sekaligus nol umpan."""
        hasil = self._buang({'possession_pct': 38, 'passes_total': 290, 'shots_total': 0,
                             'corners': 0, 'fouls': 12})
        self.assertEqual(hasil['possession_pct'], 38)
        self.assertEqual(hasil['shots_total'], 0)
        self.assertEqual(hasil['corners'], 0)

    def test_laga_normal_lewat_apa_adanya(self):
        asli = {'possession_pct': 57, 'passes_total': 512, 'shots_total': 14}
        self.assertEqual(self._buang(dict(asli)), asli)

    def test_none_diperlakukan_sama_dengan_nol(self):
        hasil = self._buang({'possession_pct': None, 'passes_total': 0, 'shots_total': 3})
        self.assertIsNone(hasil['shots_total'])


class EspnPenyaringInkrementalTests(TestCase):
    """Penyaring 'sudah selesai & pernah ditarik' di pull_match_events_espn.

    Command ini jalan 84x/hari dan dulu narik ulang SEMUA laga selesai tiap
    kali — ~1.900 panggilan ke API yang nggak resmi, plus nimpa RawPayload
    yang isinya sama persis.

    Test paling penting di kelas ini `test_laga_live_yang_udah_ditarik_tetep_ditarik_lagi`.
    Kalau penyaringnya cuma ngecek "pernah ditarik" tanpa ngecek status, laga
    yang ditarik waktu masih jalan bakal dilewati SELAMANYA dan datanya beku
    di potret menit-60 — salah, dan diam.
    """

    def setUp(self):
        from matches.management.commands.pull_match_events_espn import Command

        self.Command = Command
        home = Team.objects.create(name='Manchester United', is_manchester_united=True)
        away = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=home,
            away_team=away,
            kickoff_at=timezone.now(),
            status=Match.Status.FINISHED,
        )
        MatchExternalRef.objects.create(
            match=self.match, source=DataSource.ESPN, external_id=740855
        )

    def _catat_ingest(self):
        MatchIngest.objects.create(match=self.match, source=DataSource.ESPN, rows=100)

    def test_selesai_dan_udah_ditarik_dilewati(self):
        self._catat_ingest()
        self.assertTrue(self.Command._already_final(740855))

    def test_selesai_tapi_belum_pernah_ditarik_tetep_ditarik(self):
        """Laga lama yang fixture-nya masuk dari provider lain: status udah FT
        tapi ESPN belum pernah nyentuh. Justru ini yang harus ditarik."""
        self.assertFalse(self.Command._already_final(740855))

    def test_laga_live_yang_udah_ditarik_tetep_ditarik_lagi(self):
        """Ini pagar terhadap pembekuan data.

        Laga yang ditarik waktu masih jalan tetep dapet baris MatchIngest.
        Kalau penyaringnya nggak ngecek status, laga itu dilewati selamanya.
        """
        self._catat_ingest()
        for status in (Match.Status.LIVE, Match.Status.HALFTIME, Match.Status.NOT_STARTED):
            Match.objects.filter(pk=self.match.pk).update(status=status)
            self.assertFalse(
                self.Command._already_final(740855),
                f'laga berstatus {status} nggak boleh dilewati',
            )

    def test_tertunda_dan_batal_nggak_dianggap_final(self):
        """Laga tertunda bisa dijadwalkan ulang dan statusnya balik ke NS,
        jadi dia harus tetep dicek tiap run."""
        self._catat_ingest()
        for status in (Match.Status.POSTPONED, Match.Status.CANCELLED):
            Match.objects.filter(pk=self.match.pk).update(status=status)
            self.assertFalse(self.Command._already_final(740855))

    def test_perpanjangan_dan_adu_penalti_dianggap_final(self):
        self._catat_ingest()
        for status in (Match.Status.EXTRA_TIME, Match.Status.PENALTIES):
            Match.objects.filter(pk=self.match.pk).update(status=status)
            self.assertTrue(self.Command._already_final(740855))

    def test_catatan_sumber_lain_nggak_ngaruh(self):
        MatchIngest.objects.create(match=self.match, source=DataSource.FOTMOB, rows=50)
        self.assertFalse(self.Command._already_final(740855))

    def test_id_nggak_dikenal_atau_ngawur(self):
        self._catat_ingest()
        for value in (999999, None, 'bukan-angka', ''):
            self.assertFalse(self.Command._already_final(value))


class EspnRetryTests(SimpleTestCase):
    """Percobaan ulang di klien ESPN.

    ESPN itu sumber paling rapuh (API tidak resmi) tapi dulu justru satu-satunya
    yang tanpa retry sama sekali. Log cron mencatat 7 kegagalan jaringan dalam
    6 hari: read timeout dan connection reset — dua-duanya sementara.
    """

    class SesiPalsu:
        """Sesi tiruan yang memutar daftar hasil: exception atau response."""

        def __init__(self, hasil):
            self.hasil = list(hasil)
            self.panggilan = 0
            self.headers = {}

        def get(self, url, params=None, timeout=None):
            self.panggilan += 1
            item = self.hasil.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class ResponsPalsu:
        def __init__(self, status=200, payload=None):
            self.status_code = status
            self._payload = payload if payload is not None else {'events': []}

        def json(self):
            return self._payload

        def raise_for_status(self):
            import requests

            if self.status_code >= 400:
                raise requests.HTTPError(f'HTTP {self.status_code}')

    def _klien(self, hasil, **kw):
        from unittest.mock import patch

        from matches.services.espn import EspnClient

        sesi = self.SesiPalsu(hasil)
        with patch('time.sleep'):  # jangan beneran nunggu waktu tes
            klien = EspnClient(session=sesi, **kw)
            return klien, sesi

    def test_timeout_dicoba_ulang_lalu_berhasil(self):
        import requests

        from unittest.mock import patch

        klien, sesi = self._klien(
            [requests.Timeout('read timeout=15'), self.ResponsPalsu(payload={'ok': 1})]
        )
        with patch('time.sleep'):
            hasil = klien._get('eng.1', 'scoreboard')
        self.assertEqual(hasil, {'ok': 1})
        self.assertEqual(sesi.panggilan, 2)
        self.assertEqual(klien.retry_count, 1)

    def test_koneksi_putus_dicoba_ulang(self):
        import requests

        from unittest.mock import patch

        klien, sesi = self._klien(
            [
                requests.ConnectionError('Connection reset by peer'),
                requests.ConnectionError('Connection reset by peer'),
                self.ResponsPalsu(payload={'ok': 2}),
            ]
        )
        with patch('time.sleep'):
            self.assertEqual(klien._get('eng.1', 'scoreboard'), {'ok': 2})
        self.assertEqual(sesi.panggilan, 3)

    def test_nyerah_setelah_batas_dan_sebut_penyebabnya(self):
        import requests

        from unittest.mock import patch

        from matches.services.espn import EspnError

        klien, sesi = self._klien([requests.Timeout('timeout')] * 3)
        with patch('time.sleep'), self.assertRaises(EspnError) as ctx:
            klien._get('eng.1', 'scoreboard')
        self.assertEqual(sesi.panggilan, 3, 'harus 1 percobaan + 2 ulangan')
        self.assertIn('3 percobaan', str(ctx.exception))

    def test_404_TIDAK_dicoba_ulang(self):
        """Error klien nggak akan berubah karena diulang — cuma buang waktu
        dan nambah tekanan ke API yang nggak resmi."""
        from unittest.mock import patch

        from matches.services.espn import EspnError

        klien, sesi = self._klien([self.ResponsPalsu(status=404)])
        with patch('time.sleep'), self.assertRaises(EspnError):
            klien._get('eng.1', 'scoreboard')
        self.assertEqual(sesi.panggilan, 1)

    def test_503_dicoba_ulang(self):
        from unittest.mock import patch

        klien, sesi = self._klien(
            [self.ResponsPalsu(status=503), self.ResponsPalsu(payload={'ok': 3})]
        )
        with patch('time.sleep'):
            self.assertEqual(klien._get('eng.1', 'scoreboard'), {'ok': 3})
        self.assertEqual(sesi.panggilan, 2)

    def test_user_agent_menyebut_identitas_bukan_nyamar_browser(self):
        klien, sesi = self._klien([self.ResponsPalsu()])
        ua = sesi.headers.get('User-Agent', '')
        self.assertIn('MU-Analytics', ua)
        for browser in ('Mozilla', 'Chrome', 'Safari', 'AppleWebKit'):
            self.assertNotIn(browser, ua, 'jangan menyamar jadi browser')


class FormasiDariKoordinatTests(SimpleTestCase):
    """Pembacaan baris formasi dari koordinat FotMob.

    Fungsi murni, jadi bisa dites tanpa DB sama sekali.
    """

    @staticmethod
    def _xi(xs):
        return [{'x': x, 'y': i * 0.09} for i, x in enumerate(xs)]

    def _label(self, xs):
        from matches.lineup_prediction import label_lines, split_lines

        return label_lines(split_lines(self._xi(xs)))

    def _formasi(self, xs):
        from matches.lineup_prediction import formation_signature, split_lines

        return formation_signature(split_lines(self._xi(xs)))

    def test_formasi_umum_kebaca_benar(self):
        for xs, harapan in [
            ([0.05] + [0.25] * 4 + [0.45] * 2 + [0.65] * 3 + [0.85], '4-2-3-1'),
            ([0.05] + [0.25] * 4 + [0.5] * 4 + [0.8] * 2, '4-4-2'),
            ([0.05] + [0.25] * 4 + [0.5] * 3 + [0.8] * 3, '4-3-3'),
            ([0.05] + [0.22] * 3 + [0.45] * 4 + [0.68] * 2 + [0.88], '3-4-2-1'),
            ([0.05] + [0.2] * 3 + [0.5] * 5 + [0.85] * 2, '3-5-2'),
        ]:
            self.assertEqual(self._formasi(xs), harapan)

    def test_double_pivot_dapat_dua_DM(self):
        """Lini tengah 2 pemain itu kasus PALING SERING (4-2-3-1), dan versi
        pertama aturan label nggak menanganinya sama sekali."""
        label = self._label([0.05] + [0.25] * 4 + [0.45] * 2 + [0.65] * 3 + [0.85])
        self.assertEqual(label[5:7], ['DM', 'DM'])
        self.assertEqual(label[7:10], ['LW', 'AM', 'RW'])

    def test_lini_tengah_lebar_jadi_sayap_kalau_bek_udah_empat(self):
        """4-4-2: bek sayap udah ada di lini belakang, jadi yang lebar di
        tengah itu SAYAP, bukan wing-back."""
        self.assertEqual(self._label([0.05] + [0.25] * 4 + [0.5] * 4 + [0.8] * 2)[5:9],
                         ['LW', 'CM', 'CM', 'RW'])

    def test_lini_tengah_lebar_jadi_wing_back_kalau_bek_cuma_tiga(self):
        self.assertEqual(self._label([0.05] + [0.22] * 3 + [0.45] * 4 + [0.68] * 2 + [0.88])[4:8],
                         ['LB', 'DM', 'DM', 'RB'])

    def test_lini_tengah_tiga_yang_bukan_menyerang_tetap_sentral(self):
        """4-3-3: lini tengah 3 itu sentral. Yang jadi sayap cuma band
        menyerang di 4-2-3-1."""
        self.assertEqual(self._label([0.05] + [0.25] * 4 + [0.5] * 3 + [0.8] * 3)[5:8],
                         ['CM', 'CM', 'CM'])

    def test_y_kecil_berarti_kiri(self):
        """Diverifikasi dari data produksi: Luke Shaw (bek kiri) y=0.125,
        Mazraoui (bek kanan) y=0.875 di laga yang sama."""
        from matches.lineup_prediction import label_lines, split_lines

        xi = [{'x': 0.05, 'y': 0.5}] + [
            {'x': 0.25, 'y': y} for y in (0.125, 0.375, 0.625, 0.875)
        ] + [{'x': 0.5, 'y': 0.5}] * 6
        self.assertEqual(label_lines(split_lines(xi))[1], 'LB')
        self.assertEqual(label_lines(split_lines(xi))[4], 'RB')

    def test_kunci_slot_bernomor_kalau_labelnya_kembar(self):
        from matches.lineup_prediction import slot_keys

        self.assertEqual(
            slot_keys(['GK', 'LB', 'CB', 'CB', 'RB', 'DM', 'DM', 'LW', 'AM', 'RW', 'CF']),
            ['GK', 'LB', 'CB1', 'CB2', 'RB', 'DM1', 'DM2', 'LW', 'AM', 'RW', 'CF'],
        )


class PrediksiSusunanTests(TestCase):
    """`predict_xi` — agregasi lintas laga."""

    def setUp(self):
        from players.models import Player

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich')
        self.pemain = [
            Player.objects.create(name=f'Pemain {i}', team=self.mu) for i in range(14)
        ]
        self.XS = [0.05] + [0.25] * 4 + [0.45] * 2 + [0.65] * 3 + [0.85]

    def _laga(self, hari_lalu, urutan_pemain, menit=90):
        from datetime import timedelta

        from matches.models import PlayerMatchStatistics

        match = Match.objects.create(
            home_team=self.mu,
            away_team=self.lawan,
            kickoff_at=timezone.now() - timedelta(days=hari_lalu),
            status=Match.Status.FINISHED,
        )
        for i, (x, idx) in enumerate(zip(self.XS, urutan_pemain)):
            PlayerMatchStatistics.objects.create(
                match=match,
                player=self.pemain[idx],
                team=self.mu,
                formation_x=x,
                formation_y=(i % 4) * 0.25 + 0.1,
                minutes_played=menit,
            )
        return match

    def test_susunan_identik_menghasilkan_keyakinan_penuh(self):
        from matches.lineup_prediction import predict_xi

        for h in (5, 10, 15, 20, 25):
            self._laga(h, list(range(11)))
        p = predict_xi(self.mu, timezone.now())
        self.assertEqual(p['formation'], '4-2-3-1')
        self.assertEqual(p['n_efektif'], 5)
        # Semua slot diisi orang yang sama tiap laga -> nggak ada yang ragu.
        self.assertTrue(all(s['confidence_pct'] is None for s in p['slots']))

    def test_pemain_pengganti_di_satu_laga_menurunkan_persentase(self):
        from matches.lineup_prediction import predict_xi

        for h in (5, 10, 15, 20):
            self._laga(h, list(range(11)))
        ganti = list(range(11))
        ganti[10] = 11  # penyerang beda di laga terlama
        self._laga(25, ganti)
        p = predict_xi(self.mu, timezone.now())
        cf = [s for s in p['slots'] if s['position'] == 'CF'][0]
        self.assertEqual(cf['confidence_pct'], 80)
        self.assertEqual(cf['frekuensi'], '4/5')

    def test_laga_berformasi_lain_dibuang(self):
        from matches.lineup_prediction import predict_xi

        for h in (5, 10, 15):
            self._laga(h, list(range(11)))
        # Satu laga 4-4-2.
        self.XS = [0.05] + [0.25] * 4 + [0.5] * 4 + [0.8] * 2
        self._laga(20, list(range(11)))
        p = predict_xi(self.mu, timezone.now())
        self.assertEqual(p['formation'], '4-2-3-1')
        self.assertEqual(p['n_efektif'], 3)
        self.assertTrue(any('formasinya beda' in w for w in p['warnings']))

    def test_laga_dengan_koordinat_bolong_dilewati(self):
        """pull_fotmob bisa kehilangan slot tanpa error kalau external ref-nya
        nggak ketemu. Laga bercoordinat 10 itu data bolong, bukan formasi
        10 pemain."""
        from matches.lineup_prediction import read_xi
        from matches.models import PlayerMatchStatistics

        m = self._laga(5, list(range(11)))
        PlayerMatchStatistics.objects.filter(match=m).order_by('id').first().delete()
        self.assertIsNone(read_xi(m, self.mu))

    def test_di_bawah_ambang_persentase_nggak_dicetak(self):
        from matches.lineup_prediction import predict_xi

        self._laga(5, list(range(11)))
        self._laga(10, list(range(11)))
        p = predict_xi(self.mu, timezone.now())
        self.assertEqual(p['n_efektif'], 2)
        self.assertTrue(all(s['confidence_pct'] is None for s in p['slots']))
        self.assertTrue(any('di bawah' in w for w in p['warnings']))

    def test_menit_kosong_membatalkan_penandaan_pemain_kunci(self):
        from matches.lineup_prediction import predict_xi

        for h in (5, 10, 15):
            self._laga(h, list(range(11)))
        self._laga(20, list(range(11)), menit=None)
        p = predict_xi(self.mu, timezone.now())
        self.assertFalse(any(s['is_key'] for s in p['slots']))
        self.assertTrue(any('pemain kunci dilewati' in w for w in p['warnings']))

    def test_satu_pemain_nggak_dipakai_di_dua_slot(self):
        from matches.lineup_prediction import predict_xi

        for h in (5, 10, 15, 20, 25):
            self._laga(h, list(range(11)))
        p = predict_xi(self.mu, timezone.now())
        ids = [s['player'].pk for s in p['slots'] if s['player']]
        self.assertEqual(len(ids), len(set(ids)))


class SnapshotPropertyTests(TestCase):
    """`before_kickoff` dan `lead_time` itu PROPERTY, bukan method.

    Regresi: command sempat memanggilnya dengan tanda kurung dan mati
    `TypeError: 'datetime.timedelta' object is not callable` — tapi baru di
    baris pesan sukses, SESUDAH snapshot-nya terlanjur tertulis. Jadi
    perintahnya kelihatan gagal padahal datanya masuk.
    """

    def setUp(self):
        from datetime import timedelta

        from matches.models import PredictionSnapshot

        mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        lawan = Team.objects.create(name='Ipswich')
        self.match = Match.objects.create(
            home_team=mu, away_team=lawan, kickoff_at=timezone.now() + timedelta(days=7)
        )
        self.snapshot = PredictionSnapshot.objects.create(match=self.match)

    def test_property_bukan_method(self):
        self.assertIsInstance(self.snapshot.before_kickoff, bool)
        self.assertTrue(self.snapshot.before_kickoff)
        self.assertGreater(self.snapshot.lead_time.total_seconds(), 0)

    def test_prediction_before_kickoff_menemukan_snapshot(self):
        self.assertEqual(self.match.prediction_before_kickoff(), self.snapshot)


class PruneRawPayloadTests(TestCase):
    """`prune_raw_payloads` — konservatif, dan default-nya nggak menghapus."""

    def setUp(self):
        from matches.models import RawPayload

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        lawan = Team.objects.create(name='Ipswich')
        self.match_baru = Match.objects.create(
            home_team=self.mu, away_team=lawan, kickoff_at=timezone.now(), season=2026
        )
        self.match_lama = Match.objects.create(
            home_team=self.mu, away_team=lawan, kickoff_at=timezone.now(), season=2019
        )
        for m, ext in ((self.match_baru, 111), (self.match_lama, 222)):
            MatchExternalRef.objects.create(
                match=m, source=DataSource.ESPN, external_id=ext
            )
            RawPayload.objects.create(
                source=DataSource.ESPN, kind='summary', key=str(ext),
                payload={'x': 1}, size_bytes=1000,
            )
        # Payload yatim: key-nya nggak nunjuk ke Match mana pun.
        RawPayload.objects.create(
            source=DataSource.ESPN, kind='summary', key='999999',
            payload={'x': 1}, size_bytes=1000,
        )

    @staticmethod
    def _jalankan(*args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('prune_raw_payloads', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_nggak_menghapus_apa_pun(self):
        from matches.models import RawPayload

        keluaran = self._jalankan()
        self.assertIn('DRY RUN', keluaran)
        self.assertEqual(RawPayload.objects.count(), 3)

    def test_yatim_terdeteksi(self):
        self.assertIn('Yatim (key nggak nyambung ke Match): 1', self._jalankan())

    def test_musim_dipertahankan_kalau_jumlahnya_di_bawah_ambang(self):
        """Cuma ada 2 musim di DB dan ambangnya 3 — nggak ada yang lama."""
        keluaran = self._jalankan()
        self.assertIn('Musim lama: nggak ada', keluaran)

    def test_apply_menghapus_yatim_tapi_menyisakan_yang_kepakai(self):
        from matches.models import RawPayload

        self._jalankan('--apply')
        sisa = set(RawPayload.objects.values_list('key', flat=True))
        self.assertEqual(sisa, {'111', '222'}, 'payload laga yang ada harus selamat')

    def test_keep_seasons_membuang_musim_di_luar_jendela(self):
        from matches.models import RawPayload

        # Dengan ambang 1, cuma musim 2026 yang dipertahankan.
        self._jalankan('--apply', '--keep-seasons', '1')
        sisa = set(RawPayload.objects.values_list('key', flat=True))
        self.assertEqual(sisa, {'111'})


class KandidatHipotesisTests(TestCase):
    """`suggest_hypotheses` — bahan buat analis, bukan klaim app.

    Aturan utamanya: kandidat cuma dibikin kalau dasarnya ADA. Lebih baik dua
    kandidat berdasar daripada lima yang satu di antaranya karangan.
    """

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich')

    def _laga(self, hari_lalu, formasi='4-2-3-1', sot=None, possession=None, gol=0):
        from datetime import timedelta

        from matches.models import MatchEvent, MatchTeamStatistics

        m = Match.objects.create(
            home_team=self.mu,
            away_team=self.lawan,
            kickoff_at=timezone.now() - timedelta(days=hari_lalu),
            status=Match.Status.FINISHED,
            home_formation=formasi,
        )
        if sot is not None or possession is not None:
            MatchTeamStatistics.objects.create(
                match=m, team=self.mu, shots_on_target=sot, possession_pct=possession
            )
        for i in range(gol):
            MatchEvent.objects.create(
                match=m, team=self.mu, event_type=MatchEvent.EventType.GOAL, minute=10 + i
            )
        return m

    def _kandidat(self):
        from matches.lineup_prediction import suggest_hypotheses

        return suggest_hypotheses(self.mu, timezone.now())

    def test_tanpa_laga_nggak_ada_kandidat(self):
        self.assertEqual(self._kandidat(), [])

    def test_formasi_jadi_kandidat_kalau_berulang(self):
        for h in (5, 10, 15):
            self._laga(h)
        teks = [k['text'] for k in self._kandidat()]
        self.assertTrue(any('4-2-3-1' in t for t in teks))

    def test_statistik_kosong_nggak_melahirkan_kandidat_karangan(self):
        """Kalau MatchTeamStatistics nggak ada, kandidat tembakan & possession
        harus absen — bukan diisi angka default."""
        for h in (5, 10, 15):
            self._laga(h)
        teks = ' '.join(k['text'] for k in self._kandidat())
        self.assertNotIn('tembakan', teks)
        self.assertNotIn('menguasai bola', teks)

    def test_possession_ngawur_dibuang_dari_rata_rata(self):
        """Laga pramusim lawan Wrexham tercatat possession 100% dengan 0
        tembakan — data rusak. Kalau ikut dirata-rata, ambangnya ngaco."""
        for h, p in ((5, 50), (10, 50), (15, 50), (20, 100)):
            self._laga(h, possession=p, sot=5)
        kandidat = [k for k in self._kandidat() if 'menguasai bola' in k['text']]
        self.assertEqual(len(kandidat), 1)
        self.assertIn('50%', kandidat[0]['text'])
        self.assertIn('nggak masuk akal', kandidat[0]['evidence_note'])

    def test_ambang_gol_ikut_rata_rata(self):
        for h, g in ((5, 2), (10, 2), (15, 2)):
            self._laga(h, gol=g)
        teks = [k['text'] for k in self._kandidat() if 'gol' in k['text']][0]
        self.assertIn('minimal 2 gol', teks)

        Match.objects.all().delete()
        for h in (5, 10, 15):
            self._laga(h, gol=0)
        teks = [k['text'] for k in self._kandidat() if 'gol' in k['text']][0]
        self.assertIn('minimal 1 gol', teks)

    def test_tiap_kandidat_bawa_kriteria_yang_TERBACA_MESIN(self):
        """Bukan cuma kalimat 'Cek: ...' buat dibaca manusia — evaluator harus
        bisa menjalankannya tanpa menebak."""
        from matches.lineup_prediction import baca_kriteria

        for h in (5, 10, 15):
            self._laga(h, sot=5, possession=55, gol=1)
        kandidat = self._kandidat()
        self.assertTrue(kandidat)
        for k in kandidat:
            self.assertIn('Dasar:', k['evidence_note'], k['text'])
            kriteria = baca_kriteria(k['evidence_note'])
            self.assertIsNotNone(
                kriteria, f'kandidat tanpa penanda terbaca-mesin: {k["text"]}'
            )
            metrik, op, ambang = kriteria
            self.assertIn(op, ('=', '>=', '>'))


class SvPersenDanUmpanPersenTests(TestCase):
    """Dua kolom halaman Statistik yang dikira mustahil, ternyata bisa.

    Sv%: `shots_faced` BUKAN penyebut yang benar. Artinya di ESPN adalah
    SELURUH tembakan ke arah gawang termasuk yang melenceng — dari 500 baris
    produksi, 492 punya shots_faced != saves + kebobolan. Dan ESPN berhenti
    mengirimnya sejak musim 2025 (semua nol).

    Umpan%: penyebutnya ADA di payload FotMob sebagai `total` di samping
    `value`, cuma tidak pernah dibaca parser.
    """

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.match = Match.objects.create(
            home_team=self.mu,
            away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now(),
        )

    def _baris(self, **kw):
        from matches.models import PlayerMatchStatistics
        from players.models import Player

        return PlayerMatchStatistics.objects.create(
            match=self.match,
            player=Player.objects.create(name=f'P{Player.objects.count()}'),
            team=self.mu,
            **kw,
        )

    def test_sv_persen_dari_saves_dan_kebobolan(self):
        self.assertEqual(self._baris(saves=2, goals_conceded=2).save_pct, 50.0)
        self.assertEqual(self._baris(saves=5, goals_conceded=4).save_pct, 55.6)
        self.assertEqual(self._baris(saves=3, goals_conceded=0).save_pct, 100.0)

    def test_kiper_yang_nggak_main_dapat_None_bukan_nol(self):
        """Di produksi ada 545 baris saves=0 & kebobolan=0 tanpa menit main.
        Kiper cadangan bukan berarti Sv%-nya 0% atau 100%."""
        self.assertIsNone(self._baris(saves=0, goals_conceded=0).save_pct)
        self.assertIsNone(self._baris().save_pct)

    def test_shots_faced_TIDAK_dipakai_buat_sv_persen(self):
        """Onana asli: shots_faced=7, saves=2, kebobolan=3. Kalau dibagi 7
        hasilnya 29%; yang benar 2 dari 5 = 40%."""
        baris = self._baris(shots_faced=7, saves=2, goals_conceded=3)
        self.assertEqual(baris.save_pct, 40.0)

    def test_umpan_persen_butuh_penyebut(self):
        self.assertEqual(self._baris(passes_accurate=72, passes_total=78).pass_pct, 92.3)
        self.assertIsNone(self._baris(passes_accurate=72).pass_pct)
        self.assertIsNone(self._baris(passes_accurate=72, passes_total=0).pass_pct)

    def test_parser_fotmob_ambil_value_dan_total(self):
        from matches.management.commands.pull_fotmob import (
            PLAYER_TOTAL_FIELDS,
            Command,
        )

        self.assertEqual(PLAYER_TOTAL_FIELDS['accurate_passes'], 'passes_total')
        # Bentuk asli dari payload produksi (Maguire 72 dari 78).
        stat = {'type': 'fractionWithPercentage', 'total': 78, 'value': 72}
        self.assertEqual(Command._coerce(stat.get('value'), 'passes_accurate'), 72)
        self.assertEqual(Command._coerce(stat.get('total'), 'passes_total'), 78)

    def test_penjaga_nol_palsu_pemain(self):
        from matches.management.commands.pull_match_events_espn import Command

        # Mustahil: nol tembakan dihadapi tapi kebobolan.
        hasil = Command._buang_nol_palsu_pemain(
            {'shots_faced': 0, 'goals_conceded': 1, 'saves': 0}
        )
        self.assertIsNone(hasil['shots_faced'])
        self.assertEqual(hasil['goals_conceded'], 1, 'field lain jangan ikut dibuang')

        # Mustahil juga: nol tembakan dihadapi tapi bikin penyelamatan.
        self.assertIsNone(
            Command._buang_nol_palsu_pemain(
                {'shots_faced': 0, 'goals_conceded': 0, 'saves': 3}
            )['shots_faced']
        )

        # Pemain lapangan yang memang nol semua: biarkan.
        utuh = Command._buang_nol_palsu_pemain(
            {'shots_faced': 0, 'goals_conceded': 0, 'saves': 0}
        )
        self.assertEqual(utuh['shots_faced'], 0)

        # Angka sah tetap tersimpan.
        self.assertEqual(
            Command._buang_nol_palsu_pemain(
                {'shots_faced': 9, 'goals_conceded': 1, 'saves': 4}
            )['shots_faced'],
            9,
        )


class EvaluatorHipotesisTests(TestCase):
    """`evaluate_hypotheses` — inti panel Cek Prediksi."""

    def setUp(self):
        from datetime import timedelta

        from matches.models import HypothesisItem, MatchTeamStatistics, PredictionSnapshot

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.match = Match.objects.create(
            home_team=self.mu,
            away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now() - timedelta(days=1),
            status=Match.Status.FINISHED,
            home_formation='4-2-3-1',
        )
        MatchTeamStatistics.objects.create(
            match=self.match, team=self.mu, shots_on_target=7, possession_pct=58
        )
        self.snapshot = PredictionSnapshot.objects.create(match=self.match)
        # created_at itu auto_now_add, jadi defaultnya SEKARANG — padahal
        # laganya kemarin. Tanpa dimundurkan, prediction_before_kickoff()
        # benar-benar menolaknya, dan itu memang perilaku yang dijaga:
        # prediksi yang dibuat sesudah peluit nggak boleh menyamar jadi
        # prediksi pra-laga.
        PredictionSnapshot.objects.filter(pk=self.snapshot.pk).update(
            created_at=self.match.kickoff_at - timedelta(hours=3)
        )
        self.snapshot.refresh_from_db()
        self.HypothesisItem = HypothesisItem

    def _hipotesis(self, teks, note, order=1):
        return self.HypothesisItem.objects.create(
            snapshot=self.snapshot, order=order, text=teks, evidence_note=note
        )

    def _jalankan(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('evaluate_hypotheses', '--match', self.match.pk, *args, stdout=out)
        return out.getvalue()

    def test_kriteria_terpenuhi_jadi_KENA(self):
        h = self._hipotesis('6 tembakan tepat sasaran', 'Dasar: x. [cek:shots_on_target>=6]')
        self._jalankan('--apply')
        h.refresh_from_db()
        self.assertEqual(h.outcome, self.HypothesisItem.Outcome.HIT)
        self.assertIn('shots_on_target = 7', h.outcome_note)
        self.assertIsNotNone(h.evaluated_at)

    def test_kriteria_tidak_terpenuhi_jadi_MELESET(self):
        h = self._hipotesis('10 tembakan tepat sasaran', 'Dasar: x. [cek:shots_on_target>=10]')
        self._jalankan('--apply')
        h.refresh_from_db()
        self.assertEqual(h.outcome, self.HypothesisItem.Outcome.MISS)

    def test_formasi_dibandingkan_sebagai_teks(self):
        kena = self._hipotesis('formasi 4-2-3-1', '[cek:formasi=4-2-3-1]', order=1)
        meleset = self._hipotesis('formasi 3-5-2', '[cek:formasi=3-5-2]', order=2)
        self._jalankan('--apply')
        kena.refresh_from_db(); meleset.refresh_from_db()
        self.assertEqual(kena.outcome, self.HypothesisItem.Outcome.HIT)
        self.assertEqual(meleset.outcome, self.HypothesisItem.Outcome.MISS)

    def test_kalimat_bebas_analis_tetap_BELUM(self):
        """App nggak pura-pura ngerti kalimat yang nggak dia tulis."""
        h = self._hipotesis('MU akan menekan tinggi di 20 menit pertama', 'Firasat saya.')
        self._jalankan('--apply')
        h.refresh_from_db()
        self.assertEqual(h.outcome, self.HypothesisItem.Outcome.PENDING)
        self.assertIn('manual', h.outcome_note)

    def test_data_belum_ada_tetap_BELUM_bukan_MELESET(self):
        """Membedakan 'nggak terjadi' dari 'belum tahu' itu penting — kalau
        keliru, hipotesis yang sah dihukum karena penarikan data telat."""
        h = self._hipotesis('xG di atas 1.5', '[cek:xg>1.5]')
        self._jalankan('--apply')
        h.refresh_from_db()
        self.assertEqual(h.outcome, self.HypothesisItem.Outcome.PENDING)
        self.assertIn('belum ada', h.outcome_note)

    def test_dry_run_nggak_menulis(self):
        h = self._hipotesis('6 tembakan', '[cek:shots_on_target>=6]')
        self._jalankan()
        h.refresh_from_db()
        self.assertEqual(h.outcome, self.HypothesisItem.Outcome.PENDING)

    def test_laga_belum_final_ditolak(self):
        from django.core.management.base import CommandError

        Match.objects.filter(pk=self.match.pk).update(status=Match.Status.LIVE)
        self._hipotesis('6 tembakan', '[cek:shots_on_target>=6]')
        with self.assertRaises(CommandError) as ctx:
            self._jalankan('--apply')
        self.assertIn('belum final', str(ctx.exception))

    def test_idempoten(self):
        h = self._hipotesis('6 tembakan', '[cek:shots_on_target>=6]')
        self._jalankan('--apply')
        waktu = self.HypothesisItem.objects.get(pk=h.pk).evaluated_at
        keluaran = self._jalankan('--apply')
        self.assertIn('sudah dinilai', keluaran)
        self.assertEqual(self.HypothesisItem.objects.get(pk=h.pk).evaluated_at, waktu)

    def test_akurasi_susunan_membedakan_dua_sebab_kosong(self):
        """Dua alasan berbeda kenapa akurasi nggak bisa dihitung, dan pesannya
        harus beda — 'kita nggak memprediksi' vs 'datanya belum masuk'."""
        from matches.models import LineupSlot
        from players.models import Player

        self._hipotesis('6 tembakan', '[cek:shots_on_target>=6]')

        # (a) snapshot nggak punya prediksi susunan sama sekali
        self.assertIn('nggak ada prediksi susunan', self._jalankan())

        # (b) prediksi ada, tapi susunan sebenarnya belum ditarik
        for i in range(11):
            LineupSlot.objects.create(
                snapshot=self.snapshot, slot=i + 1, position='CM',
                player=Player.objects.create(name=f'Pemain {i}', team=self.mu),
            )
        self.assertIn('belum masuk', self._jalankan())


class PrediksiSesudahPeluitDitolakTests(TestCase):
    """`prediction_before_kickoff()` harus menolak snapshot pasca-kickoff.

    Ini pagar yang bikin Cek Prediksi berarti. Kalau prediksi yang ditulis
    SESUDAH laga bisa ikut terhitung, panel itu nggak membuktikan apa-apa.
    Ketahuan waktu nulis test evaluator: snapshot dibuat dengan auto_now_add
    buat laga kemarin, dan command-nya benar-benar menolak.
    """

    def setUp(self):
        from datetime import timedelta

        from matches.models import PredictionSnapshot

        mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.match = Match.objects.create(
            home_team=mu,
            away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now() - timedelta(days=1),
            status=Match.Status.FINISHED,
        )
        self.PredictionSnapshot = PredictionSnapshot
        self.timedelta = timedelta

    def _snapshot(self, jam_sebelum):
        s = self.PredictionSnapshot.objects.create(match=self.match)
        self.PredictionSnapshot.objects.filter(pk=s.pk).update(
            created_at=self.match.kickoff_at - self.timedelta(hours=jam_sebelum)
        )
        return self.PredictionSnapshot.objects.get(pk=s.pk)

    def test_snapshot_sesudah_peluit_diabaikan(self):
        sesudah = self._snapshot(-2)  # 2 jam SESUDAH kickoff
        self.assertFalse(sesudah.before_kickoff)
        self.assertIsNone(self.match.prediction_before_kickoff())

    def test_yang_dipakai_adalah_versi_terakhir_sebelum_peluit(self):
        self._snapshot(48)
        terbaru = self._snapshot(2)
        self._snapshot(-1)  # pasca-peluit, harus diabaikan
        self.assertEqual(self.match.prediction_before_kickoff(), terbaru)


class HeartbeatSumberTests(TestCase):
    """Feed sehat yang nggak punya data baru bukan feed mati.

    Regresi: sesudah penyaring inkremental dipasang, ESPN melewati semua laga
    selesai — jadi MatchIngest nggak tersentuh dan kartu Kesehatan Sumber
    bilang "berhenti 12 jam lalu" padahal command-nya sukses tiap 10 menit.
    Alarm palsu buat feed yang paling sering jalan, dan ini pengulangan bug 4.7
    dengan sebab yang beda.
    """

    def setUp(self):
        from datetime import timedelta

        from matches.models import MatchIngest, SourceHeartbeat

        mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.match = Match.objects.create(
            home_team=mu, away_team=Team.objects.create(name='Ipswich'),
            kickoff_at=timezone.now(),
        )
        # Penarikan terakhir 5 hari lalu — di atas ambang 'berhenti' ESPN (12 jam).
        ingest = MatchIngest.objects.create(
            match=self.match, source=DataSource.ESPN, rows=10
        )
        MatchIngest.objects.filter(pk=ingest.pk).update(
            ingested_at=timezone.now() - timedelta(days=5)
        )
        self.SourceHeartbeat = SourceHeartbeat

    def _status(self):
        from matches.source_health import source_health

        return {r['source']: r['status'] for r in source_health()}[DataSource.ESPN]

    def test_tanpa_heartbeat_terbaca_berhenti(self):
        self.assertEqual(self._status(), 'berhenti')

    def test_heartbeat_baru_bikin_normal_lagi(self):
        self.SourceHeartbeat.objects.create(
            source=DataSource.ESPN, note='8 fixture dicek, 0 diproses, 8 dilewati'
        )
        self.assertEqual(self._status(), 'normal')

    def test_heartbeat_lama_nggak_menutupi_feed_yang_beneran_mati(self):
        """Heartbeat cuma menang kalau lebih baru. Kalau command-nya sendiri
        berhenti jalan, kartunya harus tetap merah."""
        from datetime import timedelta

        beat = self.SourceHeartbeat.objects.create(source=DataSource.ESPN)
        self.SourceHeartbeat.objects.filter(pk=beat.pk).update(
            last_ok_at=timezone.now() - timedelta(days=3)
        )
        self.assertEqual(self._status(), 'berhenti')


class BebanRotasiTests(TestCase):
    """Rumus LV-08 dari inventaris kartu, ditulis sebagai fungsi murni.

    Handoff Tahap 3 minta begitu eksplisit: "Tulis sebagai fungsi murni dengan
    tes, bukan query yang tersebar di UI." Satu rumus ini dirujuk tiga kartu:
    kolom Beban 14 hr (SQ-02), Kandidat Rotasi (LV-08), Duel Kunci (PR-08).
    """

    def test_rumus_persis_seperti_handoff(self):
        """skor = 0,5 x beban + 0,3 x kepadatan + 0,2 x riwayat,
        dengan beban = menit / 450."""
        from matches.workload import skor_rotasi

        # Tiga laga penuh + jadwal padat + riwayat = semua komponen maksimum.
        self.assertEqual(skor_rotasi(450, True, True), 1.0)
        # Cuma beban.
        self.assertEqual(skor_rotasi(450, False, False), 0.5)
        # Cuma kepadatan.
        self.assertEqual(skor_rotasi(0, True, False), 0.3)
        # Cuma riwayat.
        self.assertEqual(skor_rotasi(0, False, True), 0.2)
        self.assertEqual(skor_rotasi(0, False, False), 0.0)

    def test_beban_di_atas_patokan_nggak_dibatasi(self):
        """600 menit memang lebih berat dari 450, dan kartunya ada justru buat
        menemukan itu — jadi komponennya sengaja nggak dipotong di 1,0."""
        from matches.workload import skor_rotasi

        self.assertGreater(skor_rotasi(600, False, False), skor_rotasi(450, False, False))

    def test_menit_kosong_nggak_bikin_error(self):
        from matches.workload import skor_rotasi

        self.assertEqual(skor_rotasi(None, False, False), 0.0)

    def test_tingkat_kemendesakan(self):
        from matches.workload import tingkat

        self.assertEqual(tingkat(1.0), 'mendesak')
        self.assertEqual(tingkat(0.5), 'mendesak')
        self.assertEqual(tingkat(0.35), 'awasi')
        self.assertEqual(tingkat(0.1), 'aman')

    def test_deteksi_cedera_otot_sengaja_sempit(self):
        """'Knock', 'Ill', 'Ankle injury' TIDAK dihitung. Kalau dimasukkan,
        hampir semua pemain punya riwayat — dan komponen yang selalu bernilai 1
        nggak membedakan apa-apa."""
        from matches.workload import cedera_otot

        for otot in ('Hamstring injury', 'Muscle injury', 'Thigh problems',
                     'Calf injury', 'Groin injury'):
            self.assertTrue(cedera_otot(otot), otot)
        for bukan in ('Knock', 'Ill', 'Ankle injury', 'Knee injury', 'Unknown',
                      'Shoulder injury', 'Corona virus', ''):
            self.assertFalse(cedera_otot(bukan), bukan)

    def test_alasan_menjelaskan_komponen_yang_aktif(self):
        from matches.workload import alasan

        teks = alasan(450, True, True)
        self.assertIn('450 menit', teks)
        self.assertIn('4 hari', teks)
        self.assertIn('otot', teks)
        self.assertNotIn('·', alasan(120, False, False))


class BebanSkuadTests(TestCase):
    """`beban_skuad` — satu-satunya fungsi di modul itu yang menyentuh DB."""

    def setUp(self):
        from datetime import timedelta

        from players.models import Player

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich')
        self.sekarang = timezone.now()
        self.timedelta = timedelta
        self.reguler = Player.objects.create(name='Reguler', team=self.mu)
        self.cadangan = Player.objects.create(name='Cadangan', team=self.mu)

    def _laga(self, hari_lalu, menit_reguler):
        from matches.models import PlayerMatchStatistics

        m = Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=self.sekarang - self.timedelta(days=hari_lalu),
            status=Match.Status.FINISHED,
        )
        PlayerMatchStatistics.objects.create(
            match=m, player=self.reguler, team=self.mu, minutes_played=menit_reguler
        )
        return m

    def test_menit_di_luar_jendela_14_hari_nggak_dihitung(self):
        from matches.workload import beban_skuad

        self._laga(3, 90)
        self._laga(20, 90)  # di luar jendela
        hasil = {r['player'].name: r for r in beban_skuad(self.mu, self.sekarang)}
        self.assertEqual(hasil['Reguler']['menit'], 90)

    def test_kepadatan_jadwal_berlaku_untuk_seluruh_tim(self):
        """Laga berikutnya sama buat semua orang, jadi komponen ini nggak
        boleh beda-beda per pemain."""
        from matches.workload import beban_skuad

        Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=self.sekarang + self.timedelta(days=2),
        )
        hasil = beban_skuad(self.mu, self.sekarang)
        self.assertTrue(all(r['jadwal_padat'] for r in hasil))

    def test_laga_jauh_bukan_jadwal_padat(self):
        from matches.workload import beban_skuad

        Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=self.sekarang + self.timedelta(days=9),
        )
        self.assertFalse(beban_skuad(self.mu, self.sekarang)[0]['jadwal_padat'])

    def test_riwayat_cedera_otot_dari_enam_bulan_terakhir(self):
        from players.models import Injury

        from matches.workload import beban_skuad

        Injury.objects.create(
            player=self.reguler, reason='Hamstring injury',
            start_date=(self.sekarang - self.timedelta(days=30)).date(),
        )
        Injury.objects.create(
            player=self.cadangan, reason='Hamstring injury',
            start_date=(self.sekarang - self.timedelta(days=400)).date(),
        )
        hasil = {r['player'].name: r for r in beban_skuad(self.mu, self.sekarang)}
        self.assertTrue(hasil['Reguler']['riwayat_otot'])
        self.assertFalse(hasil['Cadangan']['riwayat_otot'], 'lebih dari 6 bulan')

    def test_urut_dari_yang_paling_mendesak(self):
        from matches.workload import beban_skuad

        self._laga(2, 90)
        self._laga(5, 90)
        hasil = beban_skuad(self.mu, self.sekarang)
        self.assertEqual(hasil[0]['player'].name, 'Reguler')
        self.assertGreaterEqual(hasil[0]['skor'], hasil[1]['skor'])


class KetersediaanFplTests(TestCase):
    """`pull_availability_fpl` — sumber ketersediaan KEDUA.

    Sebelum ini cuma Highlightly, jadi panel Konflik Sumber nggak pernah bisa
    terisi. Dan Highlightly ternyata bukan feed ketersediaan sama sekali: dia
    riwayat karier, entri terbaru Mason Mount berakhir September 2021 — itu
    yang bikin 263 dari 264 entri MU berstatus RETURNED.
    """

    def setUp(self):
        from players.models import Player

        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.bruno = Player.objects.create(name='Bruno Fernandes', team=self.mu, is_active=True)
        self.amad = Player.objects.create(name='Amad Diallo', team=self.mu, is_active=True)
        self.muda = Player.objects.create(name='Pemain Muda', team=self.mu, is_active=True)

    def _payload(self):
        return {
            'teams': [{'id': 16, 'name': 'Man Utd'}],
            'elements': [
                {'team': 16, 'first_name': 'Bruno', 'second_name': 'Borges Fernandes',
                 'web_name': 'B.Fernandes', 'status': 'a', 'news': '',
                 'news_added': '2026-07-23T12:01:23.321726Z',
                 'chance_of_playing_next_round': 100},
                {'team': 16, 'first_name': 'Amad', 'second_name': 'Diallo',
                 'web_name': 'Diallo', 'status': 'd',
                 'news': 'Unspecified injury - 75% chance of playing',
                 'news_added': '2026-08-22T11:00:08.617283Z',
                 'chance_of_playing_next_round': 75},
            ],
        }

    def _jalankan(self):
        from io import StringIO
        from unittest.mock import patch

        from django.core.management import call_command

        class RespPalsu:
            status_code = 200

            def raise_for_status(self):
                pass

            @staticmethod
            def json():
                return KetersediaanFplTests._payload_statis

        KetersediaanFplTests._payload_statis = self._payload()
        out = StringIO()
        with patch('requests.get', return_value=RespPalsu()):
            call_command('pull_availability_fpl', stdout=out)
        return out.getvalue()

    def test_status_dipetakan(self):
        from players.models import DataSource, PlayerAvailability

        self._jalankan()
        a = {p.player.name: p for p in PlayerAvailability.objects.filter(source=DataSource.FPL)}
        self.assertEqual(a['Bruno Fernandes'].status, PlayerAvailability.Status.FIT)
        self.assertEqual(a['Amad Diallo'].status, PlayerAvailability.Status.DOUBTFUL)
        self.assertEqual(a['Amad Diallo'].chance_pct, 75)

    def test_umur_data_dari_SUMBER_bukan_waktu_tarik(self):
        """`news_added` FPL itu kapan KABARNYA berubah, bukan kapan cron jalan.
        Ini yang dipakai kolom 'umur data' di panel Konflik Sumber."""
        from players.models import DataSource, PlayerAvailability

        self._jalankan()
        amad = PlayerAvailability.objects.get(
            player=self.amad, source=DataSource.FPL
        )
        self.assertIsNotNone(amad.source_updated_at)
        self.assertEqual(amad.source_updated_at.year, 2026)
        self.assertEqual(amad.source_updated_at.month, 8)
        self.assertNotEqual(amad.source_updated_at, amad.fetched_at)

    def test_pemain_di_luar_cakupan_ditandai_TIDAK_DICAKUP_bukan_bugar(self):
        """Diam-diam menganggap pemain yang nggak dicakup sebagai 'bugar' itu
        persis jenis kesalahan yang bikin panel ini nggak bisa dipercaya."""
        from players.models import DataSource, PlayerAvailability

        self._jalankan()
        muda = PlayerAvailability.objects.get(player=self.muda, source=DataSource.FPL)
        self.assertEqual(muda.status, PlayerAvailability.Status.UNKNOWN)
        self.assertNotEqual(muda.status, PlayerAvailability.Status.FIT)

    def test_nama_resmi_FPL_dicocokkan_ke_nama_umum(self):
        """FPL nulis 'Bruno Borges Fernandes', DB kita 'Bruno Fernandes'."""
        from players.models import DataSource, PlayerAvailability

        self._jalankan()
        self.assertTrue(
            PlayerAvailability.objects.filter(
                player=self.bruno, source=DataSource.FPL
            ).exists()
        )

    def test_idempoten(self):
        from players.models import DataSource, PlayerAvailability

        self._jalankan()
        n = PlayerAvailability.objects.filter(source=DataSource.FPL).count()
        self._jalankan()
        self.assertEqual(PlayerAvailability.objects.filter(source=DataSource.FPL).count(), n)


class KonvensiSkorTests(TestCase):
    """United selalu ditulis lebih dulu — prinsip lintas halaman.

    Ditulis sekali di `matches/scoreline.py`. Tanpa helper terpusat, "2-1"
    berubah arti diam-diam antar kartu dan pembaca tidak punya cara tahu mana
    yang terbalik.
    """

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town', short_name='Ipswich')

    def _laga(self, kandang, mu_gol, lawan_gol):
        return Match.objects.create(
            home_team=self.mu if kandang else self.lawan,
            away_team=self.lawan if kandang else self.mu,
            home_score=mu_gol if kandang else lawan_gol,
            away_score=lawan_gol if kandang else mu_gol,
            kickoff_at=timezone.now(),
            status=Match.Status.FINISHED,
        )

    def test_skor_selalu_mu_dulu_walau_tandang(self):
        from matches import scoreline

        self.assertEqual(scoreline.skor_teks(self._laga(True, 2, 0)), '2–0')
        # Laga tandang: di DB tersimpan 0-2, tapi harus dibaca 2-0.
        self.assertEqual(scoreline.skor_teks(self._laga(False, 2, 0)), '2–0')

    def test_hasil_dari_sudut_pandang_mu(self):
        from matches import scoreline

        self.assertEqual(scoreline.hasil(self._laga(False, 2, 0)), 'W')
        self.assertEqual(scoreline.hasil(self._laga(True, 0, 2)), 'L')
        self.assertEqual(scoreline.hasil(self._laga(True, 1, 1)), 'D')

    def test_belum_ada_skor_tidak_mengarang_nol(self):
        from matches import scoreline

        m = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now()
        )
        self.assertEqual(scoreline.skor(m), (None, None))
        self.assertIsNone(scoreline.hasil(m))


class NilaiPemainTests(SimpleTestCase):
    """PS-03 / LV-06.

    Yang paling penting: baris yang kolomnya kosong TIDAK boleh keluar 6,0.
    Nilai 6,0 dari data kosong kelihatan persis seperti nilai 6,0 dari
    penampilan biasa-biasa saja, dan itu jenis kebohongan yang paling sulit
    ketahuan.
    """

    def test_baris_kosong_tidak_jadi_enam_koma_nol(self):
        from matches import ratings

        hasil = ratings.nilai({'minutes_played': 90}, 'CM')
        self.assertIsNone(hasil['nilai'])
        self.assertFalse(hasil['cukup_data'])

    def test_aksi_positif_menaikkan(self):
        from matches import ratings

        hasil = ratings.nilai(
            {'minutes_played': 90, 'goals': 1, 'assists': 1, 'key_passes': 2,
             'duels_won': 4, 'duels_lost': 1},
            'CF',
        )
        self.assertTrue(hasil['cukup_data'])
        self.assertGreater(hasil['nilai'], ratings.DASAR)
        self.assertIn('gol', ' '.join(hasil['kontribusi']))

    def test_kiper_dan_penyerang_tidak_dinilai_dengan_patokan_sama(self):
        from matches import ratings

        stat = {'minutes_played': 90, 'saves': 5, 'goals_conceded': 0, 'passes_accurate': 20}
        kiper = ratings.nilai(stat, 'GK')
        penyerang = ratings.nilai(stat, 'CF')
        # Penyelamatan tidak punya bobot buat penyerang, jadi angkanya harus beda.
        self.assertNotEqual(kiper['nilai'], penyerang['nilai'])

    def test_nilai_dibatasi_satu_sampai_sepuluh(self):
        from matches import ratings

        hasil = ratings.nilai(
            {'minutes_played': 90, 'goals': 9, 'assists': 5, 'key_passes': 9}, 'CF'
        )
        self.assertLessEqual(hasil['nilai'], ratings.MAKS_NILAI)


    def test_cadangan_yang_tidak_turun_tidak_dinilai(self):
        """Nol menit itu bukan penampilan buruk, itu bukan penampilan.

        Baris statistik cadangan berisi nol di mana-mana; kalau nol dianggap
        data, hasilnya 6,0 — angka yang persis sama dengan pemain yang main
        90 menit tanpa menonjol.
        """
        from matches import ratings

        hasil = ratings.nilai(
            {'minutes_played': 0, 'goals': 0, 'assists': 0, 'duels_won': 0}, 'CM'
        )
        self.assertIsNone(hasil['nilai'])
        self.assertFalse(hasil['bermain'])

    def test_peluang_tercipta_dan_umpan_kunci_tidak_dihitung_dua_kali(self):
        """Dua kolom itu angka yang sama di data kita (55 dari 55 baris identik).

        Memberi bobot ke dua-duanya bikin gelandang kreatif menembus
        langit-langit nilai gara-gara satu umpan dihitung dua kali.
        """
        from matches import ratings

        dasar = {'minutes_played': 90, 'goals': 1, 'assists': 1}
        cuma_cc = ratings.nilai({**dasar, 'chances_created': 4}, 'CM')
        cuma_kp = ratings.nilai({**dasar, 'key_passes': 4}, 'CM')
        keduanya = ratings.nilai({**dasar, 'chances_created': 4, 'key_passes': 4}, 'CM')

        self.assertEqual(cuma_cc['nilai'], cuma_kp['nilai'])
        self.assertEqual(keduanya['nilai'], cuma_cc['nilai'])

    def test_nilai_ditulis_dengan_koma(self):
        from matches import ratings

        self.assertEqual(ratings.teks_nilai(7.25), '7,2')
        self.assertEqual(ratings.teks_nilai(None), '–')


class NilaiSkuadTests(TestCase):
    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=2, away_score=0,
        )

    def _stat(self, nama, menit, **kolom):
        from matches.models import PlayerMatchStatistics

        p = Player.objects.create(name=nama, team=self.mu, position=kolom.pop('position', 'CM'))
        return PlayerMatchStatistics.objects.create(
            match=self.match, player=p, team=self.mu, minutes_played=menit, **kolom
        )

    def test_sampel_kecil_tidak_ditandai_tertinggi(self):
        """Pemain masuk menit 88 lalu mencetak gol akan selalu menang kalau
        diikutkan — dan 'pemain terbaik' versi itu bikin panelnya tak berguna."""
        from matches import ratings

        self._stat('Starter', 90, goals=1, assists=1, key_passes=3)
        self._stat('Pengganti', 5, goals=2, assists=1, key_passes=1)

        hasil = ratings.nilai_skuad(
            self.match.player_statistics.select_related('player')
        )
        tertinggi = [r for r in hasil if r['tertinggi']]
        self.assertEqual(len(tertinggi), 1)
        self.assertEqual(tertinggi[0]['player'].name, 'Starter')

    def test_tanpa_nilai_selalu_di_bawah(self):
        from matches import ratings

        self._stat('Berdata', 90, goals=1, assists=1, key_passes=2)
        self._stat('Kosong', 90)

        hasil = ratings.nilai_skuad(
            self.match.player_statistics.select_related('player')
        )
        self.assertEqual(hasil[-1]['player'].name, 'Kosong')
        self.assertIsNone(hasil[-1]['nilai'])


class NilaiSkuadUrutanTests(TestCase):
    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=1, away_score=0,
        )

    def test_tiga_keadaan_tiga_tempat(self):
        """Bernilai → data kurang → tidak turun. Urutannya harus begitu."""
        from matches import ratings
        from matches.models import PlayerMatchStatistics

        def stat(nama, **kolom):
            p = Player.objects.create(name=nama, team=self.mu, position='CM')
            PlayerMatchStatistics.objects.create(
                match=self.match, player=p, team=self.mu, **kolom
            )

        stat('Cadangan', minutes_played=0)
        stat('Tanpa data', minutes_played=90)
        stat('Bernilai', minutes_played=90, goals=1, assists=1, duels_won=3)

        hasil = ratings.nilai_skuad(self.match.player_statistics.select_related('player'))
        self.assertEqual(
            [r['player'].name for r in hasil], ['Bernilai', 'Tanpa data', 'Cadangan']
        )
        self.assertFalse(hasil[-1]['bermain'])
        self.assertTrue(hasil[1]['bermain'])


class AngkaPenentuTests(TestCase):
    """PS-02 — empat metrik yang paling menyimpang dari kebiasaan musim.

    Catatan buat yang menulis tes di sini: riwayat harus BERVARIASI. Kolom
    yang nilainya identik di seluruh musim punya simpangan baku nol, dan
    modulnya sengaja melewatinya — di data sungguhan, metrik sepak bola tidak
    pernah punya varians nol, jadi kolom seperti itu hampir pasti artefak
    (kolom yang diisi nilai default), bukan konsistensi luar biasa. Menampilkan
    artefak sebagai "paling menyimpang" akan menaruhnya di puncak kartu.
    """

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')

    def _laga(self, hari_lalu, **kolom):
        from datetime import timedelta

        from matches.models import MatchTeamStatistics

        m = Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=timezone.now() - timedelta(days=hari_lalu),
            season=2026, status=Match.Status.FINISHED, home_score=1, away_score=0,
        )
        MatchTeamStatistics.objects.create(match=m, team=self.mu, **kolom)
        MatchTeamStatistics.objects.create(match=m, team=self.lawan, shots_total=8)
        return m

    def _riwayat(self, tembakan, **tetap):
        """Delapan laga dengan tembakan bervariasi."""
        for i, t in enumerate(tembakan):
            kolom = {k: v[i] if isinstance(v, list) else v for k, v in tetap.items()}
            self._laga(i + 1, shots_total=t, **kolom)

    def test_menolak_menjawab_kalau_sampelnya_kurang(self):
        """Dari tiga laga, satu laga aneh menggeser rata-ratanya sendiri."""
        from matches import key_numbers

        self._riwayat([9, 10, 11])
        target = self._laga(0, shots_total=25)

        self.assertEqual(key_numbers.untuk_laga(target), [])

    def test_metrik_paling_menyimpang_yang_dipilih(self):
        from matches import key_numbers

        self._riwayat(
            [8, 9, 10, 11, 12, 10, 9, 11],
            possession_pct=[54, 55, 56, 55, 54, 56, 55, 55],
        )
        target = self._laga(0, shots_total=25, possession_pct=55)

        hasil = key_numbers.untuk_laga(target)
        self.assertTrue(hasil)
        self.assertEqual(hasil[0]['kunci'], 'shots_total')
        self.assertEqual(hasil[0]['arah'], 'untung')

    def test_metrik_merugikan_ditandai_merah(self):
        from matches import key_numbers

        self._riwayat(
            [8, 9, 10, 11, 12, 10, 9, 11],
            fouls=[8, 9, 10, 9, 8, 11, 10, 9],
        )
        target = self._laga(0, shots_total=10, fouls=22)

        hasil = key_numbers.untuk_laga(target)
        pelanggaran = next(h for h in hasil if h['kunci'] == 'fouls')
        self.assertEqual(pelanggaran['arah'], 'rugi')

    def test_varians_nol_dilewati_bukan_dianggap_paling_menyimpang(self):
        """Kolom yang seluruh musimnya bernilai sama itu artefak, bukan pola."""
        from matches import key_numbers

        self._riwayat([8, 9, 10, 11, 12, 10, 9, 11], corners=5)
        target = self._laga(0, shots_total=10, corners=14)

        hasil = key_numbers.untuk_laga(target)
        self.assertNotIn('corners', [h['kunci'] for h in hasil])

    def test_laga_sendiri_tidak_ikut_jadi_pembanding(self):
        """Memasukkan laganya sendiri menarik rata-rata ke nilai yang diuji."""
        from matches import key_numbers
        from matches.models import MatchTeamStatistics

        self._riwayat([10] * 4 + [10, 10, 10, 10])
        # Riwayat sengaja dibuat bervariasi lewat kolom lain supaya z terhitung.
        MatchTeamStatistics.objects.filter(team=self.mu).update(possession_pct=55)
        for i, b in enumerate(MatchTeamStatistics.objects.filter(team=self.mu)):
            b.shots_total = 8 + (i % 5)
            b.save(update_fields=['shots_total'])

        target = self._laga(0, shots_total=30)
        riwayat = list(
            MatchTeamStatistics.objects.filter(team=self.mu, match__season=2026)
            .exclude(match=target)
        )
        rata_seharusnya = sum(r.shots_total for r in riwayat) / len(riwayat)

        baris = MatchTeamStatistics.objects.get(match=target, team=self.mu)
        hasil = key_numbers.hitung(baris, None, riwayat, [])
        tembakan = next(h for h in hasil if h['kunci'] == 'shots_total')
        self.assertAlmostEqual(tembakan['rata'], rata_seharusnya)
        self.assertLess(tembakan['rata'], 30)


class LaporanTests(TestCase):
    """Laporan Pertandingan — dihasilkan tanpa campur tangan manual."""

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town', short_name='Ipswich')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=2, away_score=0,
            league_name='Premier League', venue='Old Trafford',
        )

    def _gol(self, nama, menit):
        from matches.models import MatchEvent

        p = Player.objects.create(name=nama, team=self.mu)
        return MatchEvent.objects.create(
            match=self.match, team=self.mu, player=p,
            event_type=MatchEvent.EventType.GOAL, minute=menit,
        )

    def test_laporan_menyebut_skor_dan_pencetak_gol(self):
        from matches import report

        gol = [self._gol('Bruno Fernandes', 23), self._gol('Rasmus Hojlund', 67)]
        hasil = report.susun(self.match, [], [], gol, [], varian=0)
        teks = ' '.join(hasil['paragraf'])
        self.assertIn('2–0', teks)
        self.assertIn('Bruno Fernandes', teks)
        self.assertIn("23'", teks)

    def test_susun_ulang_tidak_mengubah_fakta(self):
        """Kalau dua versi bisa berbeda faktanya, salah satunya bohong."""
        from matches import report

        gol = [self._gol('Bruno Fernandes', 23)]
        versi = [
            report.susun(self.match, [], [], gol, [], varian=v)
            for v in range(report.JUMLAH_VARIAN)
        ]
        for v in versi:
            self.assertIn('2–0', ' '.join(v['paragraf']))
            self.assertIn('Bruno Fernandes', ' '.join(v['paragraf']))
        # Susunannya memang harus berbeda, kalau tidak tombolnya tidak berguna.
        self.assertGreater(len({v['judul'] for v in versi}), 1)

    def test_tidak_mengarang_klausa_tanpa_data(self):
        """Laga tanpa event gol tidak boleh menyebut pencetak gol."""
        from matches import report

        hasil = report.susun(self.match, [], [], [], [], varian=0)
        teks = ' '.join(hasil['paragraf'])
        self.assertNotIn('Gol United datang lewat', teks)
        self.assertFalse(hasil['lengkap'])

    def test_laga_tandang_tetap_ditulis_united_dulu(self):
        from matches import report

        m = Match.objects.create(
            home_team=self.lawan, away_team=self.mu, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=0, away_score=3,
        )
        hasil = report.susun(m, [], [], [], [], varian=0)
        self.assertTrue(hasil['identitas']['judul'].startswith('Manchester United'))
        self.assertIn('3–0', hasil['identitas']['judul'])


class MomenSistemTests(TestCase):
    """PS-04 — detektor pada data akhir laga."""

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=3, away_score=0,
        )

    def test_pencetak_gol_ganda_terdeteksi(self):
        from matches import moments
        from matches.models import PlayerMatchStatistics

        p = Player.objects.create(name='Rasmus Hojlund', team=self.mu, position='CF')
        s = PlayerMatchStatistics.objects.create(
            match=self.match, player=p, team=self.mu, minutes_played=90, goals=2
        )
        hasil = moments.deteksi(self.match, None, None, [], [], [s])
        self.assertTrue(any('2 gol' in t[2] for t in hasil))

    def test_temuan_sistem_tidak_menumpuk_saat_dijalankan_ulang(self):
        from matches import moments
        from matches.models import PlayerMatchStatistics, SavedMoment

        p = Player.objects.create(name='Rasmus Hojlund', team=self.mu, position='CF')
        s = PlayerMatchStatistics.objects.create(
            match=self.match, player=p, team=self.mu, minutes_played=90, goals=2
        )
        temuan = moments.deteksi(self.match, None, None, [], [], [s])
        moments.segarkan(self.match, temuan)
        moments.segarkan(self.match, temuan)
        moments.segarkan(self.match, temuan)
        self.assertEqual(SavedMoment.objects.filter(match=self.match).count(), 1)

    def test_temuan_sistem_masuk_tanpa_tercentang(self):
        """Kalau default-nya tercentang, prompt terisi sendiri oleh hal-hal
        yang belum dibaca siapa pun."""
        from matches import moments
        from matches.models import PlayerMatchStatistics, SavedMoment

        p = Player.objects.create(name='Rasmus Hojlund', team=self.mu, position='CF')
        s = PlayerMatchStatistics.objects.create(
            match=self.match, player=p, team=self.mu, minutes_played=90, goals=2
        )
        moments.segarkan(self.match, moments.deteksi(self.match, None, None, [], [], [s]))
        self.assertFalse(SavedMoment.objects.get(match=self.match).selected)

    def test_momen_analis_tidak_disentuh_detektor(self):
        from matches import moments
        from matches.models import SavedMoment

        SavedMoment.objects.create(
            match=self.match, minute=61, text='Perubahan bentuk jadi 4-2-2-2',
            origin=SavedMoment.Asal.ANALIS, selected=True,
        )
        moments.segarkan(self.match, [])
        m = SavedMoment.objects.get(match=self.match)
        self.assertEqual(m.origin, SavedMoment.Asal.ANALIS)
        self.assertTrue(m.selected)


class GeneratorPromptTests(TestCase):
    """PS-05 — urutan blok dan aturan teksnya adalah isinya."""

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town', short_name='Ipswich')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.lawan, kickoff_at=timezone.now(),
            status=Match.Status.FINISHED, home_score=2, away_score=0,
            league_name='Premier League', venue='Old Trafford',
        )

    def test_urutan_blok_dipertahankan(self):
        from matches import prompts

        teks = prompts.susun(self.match, [], [], [])
        urutan = [
            teks.index('GAYA VISUAL'),
            teks.index('ATURAN TEKS'),
            teks.index('LAGA'),
            teks.index('DATA YANG BOLEH DIPAKAI'),
            teks.index('ISI TIAP SLIDE'),
            teks.index('FOOTER'),
        ]
        self.assertEqual(urutan, sorted(urutan))

    def test_aturan_teks_datang_sebelum_datanya(self):
        """Instruksi 'jangan bulatkan' yang datang setelah angkanya dibaca
        jauh lebih sering diabaikan."""
        from matches import prompts

        teks = prompts.susun(self.match, [], [], [])
        self.assertLess(teks.index('ATURAN TEKS'), teks.index('DATA YANG BOLEH DIPAKAI'))

    def test_foto_laga_diarahkan_bukan_dilarang(self):
        """Handoff aslinya melarang foto. Dicabut atas permintaan user: alur
        kerjanya melampirkan foto laga sendiri, dan slide teks saja terlalu
        kering. Yang tersisa cuma arahan supaya foto lampiran yang dipakai."""
        from matches import prompts

        for tipe in prompts.TIPE:
            teks = prompts.susun(self.match, [], [], [], tipe=tipe)
            self.assertIn('Foto laga dilampirkan', teks, tipe)
            self.assertNotIn('JANGAN memakai foto pemain', teks, tipe)

    def test_wajah_generatif_tetap_dicegah(self):
        """Foto asli boleh, wajah karangan tidak — hasilnya nggak pernah mirip."""
        from matches import prompts

        teks = prompts.susun(self.match, [], [], [])
        self.assertIn('mengarang wajah pemain secara generatif', teks)

    def test_istilah_inggris_boleh_dicampur(self):
        """Memaksa terjemahan bikin pembaca berhenti — 'simpangan baku' buktinya."""
        from matches import prompts

        teks = prompts.susun(self.match, [], [], [])
        self.assertIn('boleh dicampur istilah Inggris', teks)
        self.assertNotIn('- Bahasa Indonesia.\n', teks)

    def test_tanpa_fakta_tercentang_prompt_melarang_mengarang(self):
        from matches import prompts

        teks = prompts.susun(self.match, [], [], [])
        self.assertIn('jangan mengarang', teks)

    def test_angka_disalin_apa_adanya(self):
        from matches import prompts

        angka = [{
            'label': 'xG', 'nilai_teks': '2,71', 'pembanding': 'rata-rata musim 1,4',
            'simpangan_kata': 'sangat jauh di atas kebiasaan', 'sd_teks': '2,1',
            'simpangan_teks': 'sangat jauh di atas kebiasaan (2,1 standard deviation)',
        }]
        teks = prompts.susun(self.match, [], angka, [], sumber='sistem')
        self.assertIn('2,71', teks)

    def test_tipe_konten_mengganti_format_bukan_datanya(self):
        from matches import prompts

        angka = [{
            'label': 'xG', 'nilai_teks': '2,71', 'pembanding': 'rata-rata musim 1,4',
            'simpangan_kata': 'sangat jauh di atas kebiasaan', 'sd_teks': '2,1',
            'simpangan_teks': 'sangat jauh di atas kebiasaan (2,1 standard deviation)',
        }]
        feed = prompts.susun(self.match, [], angka, [], tipe='feed', sumber='sistem')
        thread = prompts.susun(self.match, [], angka, [], tipe='thread', sumber='sistem')
        self.assertIn('2,71', feed)
        self.assertIn('2,71', thread)
        self.assertNotEqual(
            feed[feed.index('ISI TIAP SLIDE'):], thread[thread.index('ISI TIAP SLIDE'):]
        )


class LangitLangitNilaiTests(SimpleTestCase):
    """Nilai yang menyentuh langit-langit tidak boleh diam-diam jadi seri.

    Dua penampilan yang mentahnya 10,2 dan 12,8 sama-sama tampil sebagai
    "10,0". Kalau urutannya juga memakai angka yang sudah dipotong, yang
    menentukan siapa di atas jadi abjad namanya.
    """

    def test_mentah_dilaporkan_dan_ditandai(self):
        from matches import ratings

        hasil = ratings.nilai(
            {'minutes_played': 90, 'goals': 4, 'assists': 3, 'chances_created': 5}, 'CM'
        )
        self.assertEqual(hasil['nilai'], ratings.MAKS_NILAI)
        self.assertGreater(hasil['mentah'], ratings.MAKS_NILAI)
        self.assertTrue(hasil['dibatasi'])

    def test_urutan_pakai_mentah_bukan_yang_sudah_dipotong(self):
        from matches import ratings

        class P:
            def __init__(self, nama):
                self.name = nama
                self.position = 'CM'

        class S:
            def __init__(self, nama, **kolom):
                self.player = P(nama)
                self.starter = True
                self.minutes_played = 90
                for k, v in kolom.items():
                    setattr(self, k, v)
            def __getattr__(self, _):
                return None

        # 'Zulkarnain' lebih hebat tapi abjadnya terakhir — kalau urutannya
        # pakai nilai yang sudah dipotong, dia kalah oleh abjad.
        hasil = ratings.nilai_skuad([
            S('Aditya', goals=3, assists=2, chances_created=4),
            S('Zulkarnain', goals=6, assists=4, chances_created=8),
        ])
        self.assertEqual(hasil[0]['player'].name, 'Zulkarnain')


class BahasaSimpanganTests(SimpleTestCase):
    """Kalimat penjelas harus bisa dibaca orang yang bukan ahli statistik.

    "1,4x simpangan baku di bawah kebiasaan" tepat secara teknis dan tidak
    berarti apa-apa buat yang membacanya — dan kalimat ini ujungnya masuk
    prompt konten yang isinya disuruh disalin persis.
    """

    def test_maknanya_ditulis_dengan_kata_biasa(self):
        from matches.key_numbers import kata_simpangan

        self.assertEqual(kata_simpangan(1.4)[0], 'jauh di atas kebiasaan')
        self.assertEqual(kata_simpangan(-2.3)[0], 'sangat jauh di bawah kebiasaan')
        self.assertEqual(kata_simpangan(0.7)[0], 'sedikit di atas kebiasaan')

    def test_istilah_teknisnya_tidak_diterjemahkan_paksa(self):
        """Kata 'simpangan baku' tidak boleh muncul di mana pun yang dibaca user."""
        from matches.key_numbers import kata_simpangan

        kata, sd = kata_simpangan(-1.4)
        self.assertNotIn('simpangan baku', kata)
        self.assertEqual(sd, '1,4')

    def test_kata_dan_angka_tidak_pernah_berselisih(self):
        """z=0,95 dan z=1,04 sama-sama tampil '1,0' kalau dibulatkan belakangan
        — dan dulu yang satu tertulis 'sedikit', yang lain 'jauh'."""
        from matches.key_numbers import kata_simpangan

        kata_a, sd_a = kata_simpangan(0.95)
        kata_b, sd_b = kata_simpangan(1.04)
        self.assertNotEqual(sd_a, sd_b)
        for skor in (0.94, 0.96, 1.03, 1.06, 1.99, 2.01):
            kata, sd = kata_simpangan(skor)
            besar = float(sd.replace(',', '.'))
            harusnya = (
                'sangat jauh' if besar >= 2.0 else 'jauh' if besar >= 1.0 else 'sedikit'
            )
            self.assertTrue(kata.startswith(harusnya), f'{skor} -> {kata} / {sd}')

    def test_rata_rata_tidak_berpresisi_palsu(self):
        """'rata-rata musim 25,27' untuk hitungan sapuan menyiratkan ketelitian
        yang tidak dimiliki angkanya. Tapi rata-rata xG memang hidup di dua
        desimal."""
        from matches.key_numbers import format_rata

        self.assertEqual(format_rata(25.27, ''), '25,3')
        self.assertEqual(format_rata(1.41, ''), '1,41')


class FormatAngkaIndonesiaTests(SimpleTestCase):
    """Semua angka yang dibaca manusia pakai koma.

    Satu angka bertitik di tengah angka-angka berkoma langsung kelihatan
    seperti salah salin — dan kalimat-kalimat ini ujungnya masuk prompt konten
    yang isinya disuruh disalin persis.
    """

    def test_simpangan_baku_pakai_koma(self):
        from matches import key_numbers

        hasil = key_numbers.hitung(
            type('B', (), {'shots_total': 25})(),
            None,
            [type('B', (), {'shots_total': v})() for v in (8, 9, 10, 11, 12, 10, 9, 11)],
            [],
        )
        self.assertTrue(hasil)
        # Yang diuji pemisah desimalnya, bukan ada-tidaknya titik di kalimat.
        angka = re.search(r'\(([\d.,]+) standard deviation\)', hasil[0]['simpangan_teks'])
        self.assertIsNotNone(angka, hasil[0]['simpangan_teks'])
        self.assertIn(',', angka.group(1))
        self.assertNotIn('.', angka.group(1))


class KalibrasiNilaiTests(TestCase):
    """Command `calibrate_ratings` — pembanding, bukan pengubah.

    Yang dijaga: dia tidak pernah menulis apa pun, dan vonisnya menolak
    kalibrasi ulang kalau perbaikannya tidak bertahan di data yang tidak
    dilatih. Faktor yang cuma bagus di data latih itu derau yang menyamar
    jadi perbaikan.
    """

    def setUp(self):
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.lawan = Team.objects.create(name='Ipswich Town')

    def _baris(self, nama, rating, laga, **kolom):
        from matches.models import PlayerMatchStatistics

        p = Player.objects.create(name=nama, team=self.mu, position=kolom.pop('position', 'CM'))
        return PlayerMatchStatistics.objects.create(
            match=laga, player=p, team=self.mu, minutes_played=90, rating=rating, **kolom
        )

    def _laga(self, i):
        from datetime import timedelta

        return Match.objects.create(
            home_team=self.mu, away_team=self.lawan,
            kickoff_at=timezone.now() - timedelta(days=i),
            season=2026, status=Match.Status.FINISHED, home_score=1, away_score=0,
        )

    def test_tanpa_data_rating_berhenti_rapi(self):
        from io import StringIO

        from django.core.management import call_command

        err = StringIO()
        call_command('calibrate_ratings', stderr=err)
        self.assertIn('pull_fotmob', err.getvalue())

    def test_melaporkan_tanpa_mengubah_bobot(self):
        from io import StringIO

        from django.core.management import call_command

        from matches import ratings

        sebelum = {k: dict(v) for k, v in ratings.BOBOT.items()}
        for i in range(4):
            laga = self._laga(i)
            self._baris(f'A{i}', 7.0, laga, goals=1, assists=1, duels_won=4)
            self._baris(f'B{i}', 6.2, laga, duels_won=2, duels_lost=3, tackles=1)

        out = StringIO()
        call_command('calibrate_ratings', '--cari', stdout=out)
        teks = out.getvalue()
        self.assertIn('rata-rata', teks)
        self.assertIn('simpangan', teks)
        # Bobotnya harus persis sama sesudah command jalan.
        self.assertEqual({k: dict(v) for k, v in ratings.BOBOT.items()}, sebelum)

    def test_pemain_tanpa_posisi_diperingatkan(self):
        """Mereka jatuh ke bobot TENGAH — membandingkan mereka berarti menilai
        bek pakai bobot gelandang lalu menyalahkan bobotnya."""
        from io import StringIO

        from django.core.management import call_command

        laga = self._laga(0)
        self._baris('Tanpa posisi', 6.5, laga, position='', goals=1, assists=1, duels_won=2)

        out = StringIO()
        call_command('calibrate_ratings', '--semua-posisi', stdout=out)
        self.assertIn('nggak punya posisi', out.getvalue())
