from django.test import TestCase
from django.utils import timezone

from matches.models import Match, PlayerMatchStatistics
from players.management.commands.merge_duplicates import Command as MergeCommand
from players.models import DataSource, Player, PlayerExternalRef, Team


class CoOccurrenceMergeTests(TestCase):
    """Penggabungan pemain yang muncul di laga & tim yang sama.

    Kasus nyata di produksi: satu orang pecah jadi dua record, satu ngumpulin
    sumber ESPN/PL/Understat, satunya cuma FotMob. Dua-duanya punya statistik
    buat laga yang sama. merge_duplicates biasa nggak nangkep karena dia
    nyaring per Player.team, sementara pasangan begini justru punya
    Player.team berbeda.
    """

    def setUp(self):
        self.cmd = MergeCommand()
        self.mu = Team.objects.create(name='Manchester United', is_manchester_united=True)
        self.other = Team.objects.create(name='Fulham')
        self.match = Match.objects.create(
            home_team=self.mu, away_team=self.other, kickoff_at=timezone.now()
        )
        # Dua record buat orang yang sama, Player.team-nya beda.
        self.a = Player.objects.create(name='Harry Wilson', team=self.other)
        self.b = Player.objects.create(name='Harry Wilson', team=self.mu)
        PlayerExternalRef.objects.create(player=self.a, source=DataSource.UNDERSTAT, external_id=1)
        PlayerExternalRef.objects.create(player=self.a, source=DataSource.ESPN, external_id=2)
        PlayerExternalRef.objects.create(player=self.b, source=DataSource.FOTMOB, external_id=3)

    def _rows(self):
        # Sengaja beda isi: yang satu punya xG, satunya punya sentuhan.
        PlayerMatchStatistics.objects.create(
            match=self.match, player=self.a, team=self.other,
            xg=0.42, minutes_played=90,
            field_sources={'xg': DataSource.UNDERSTAT, 'minutes_played': DataSource.UNDERSTAT},
        )
        PlayerMatchStatistics.objects.create(
            match=self.match, player=self.b, team=self.other,
            touches=61, rating=7.4,
            field_sources={'touches': DataSource.FOTMOB, 'rating': DataSource.FOTMOB},
        )

    def test_terdeteksi_walau_player_team_beda(self):
        self._rows()
        found = self.cmd._merge_co_occurring(apply_changes=False)
        self.assertEqual(found, 1)
        self.assertEqual(Player.objects.filter(name='Harry Wilson').count(), 2)

    def test_setelah_digabung_tinggal_satu_pemain(self):
        self._rows()
        self.cmd._merge_co_occurring(apply_changes=True)
        self.assertEqual(Player.objects.filter(name='Harry Wilson').count(), 1)

    def test_isi_kedua_baris_disatukan_bukan_dibuang(self):
        """Ini inti masalahnya: absorb() bakal ngehapus baris yang bentrok
        unique (match, player). Kalau nggak digabung dulu, salah satu sumber
        hilang — xG-nya lenyap atau sentuhannya lenyap."""
        self._rows()
        self.cmd._merge_co_occurring(apply_changes=True)

        rows = PlayerMatchStatistics.objects.filter(match=self.match)
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertEqual(row.xg, 0.42)          # dari Understat
        self.assertEqual(row.touches, 61)        # dari FotMob
        self.assertEqual(row.rating, 7.4)
        self.assertEqual(row.minutes_played, 90)

    def test_jejak_sumber_ikut_tergabung(self):
        self._rows()
        self.cmd._merge_co_occurring(apply_changes=True)
        row = PlayerMatchStatistics.objects.get(match=self.match)
        self.assertEqual(row.field_sources.get('xg'), DataSource.UNDERSTAT)
        self.assertEqual(row.field_sources.get('touches'), DataSource.FOTMOB)

    def test_semua_external_ref_pindah_ke_yang_dipertahankan(self):
        self._rows()
        self.cmd._merge_co_occurring(apply_changes=True)
        kept = Player.objects.get(name='Harry Wilson')
        self.assertEqual(
            sorted(r.source for r in kept.external_refs.all()),
            sorted([DataSource.ESPN, DataSource.FOTMOB, DataSource.UNDERSTAT]),
        )

    def test_nama_sama_tapi_beda_laga_nggak_digabung(self):
        """Pengaman: bukti identitasnya adalah muncul di laga YANG SAMA."""
        other_match = Match.objects.create(
            home_team=self.other, away_team=self.mu, kickoff_at=timezone.now()
        )
        PlayerMatchStatistics.objects.create(match=self.match, player=self.a, team=self.other)
        PlayerMatchStatistics.objects.create(match=other_match, player=self.b, team=self.other)
        self.assertEqual(self.cmd._merge_co_occurring(apply_changes=False), 0)

    def test_tim_beda_di_laga_sama_nggak_digabung(self):
        """Dua pemain senama yang beneran main lawan satu sama lain."""
        PlayerMatchStatistics.objects.create(match=self.match, player=self.a, team=self.other)
        PlayerMatchStatistics.objects.create(match=self.match, player=self.b, team=self.mu)
        self.assertEqual(self.cmd._merge_co_occurring(apply_changes=False), 0)
