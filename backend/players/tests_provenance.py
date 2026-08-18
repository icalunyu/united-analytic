from django.test import SimpleTestCase

from players.models import DataSource
from players.provenance import describe_sources, resolve_updates


class ResolveUpdatesTests(SimpleTestCase):
    """Prioritas sumber per field.

    Sebelum ini provider yang jalan terakhir menang tanpa jejak: di produksi
    ada 5.678 baris yang punya xg (Understat) sekaligus rating (FotMob), dan
    nilai xg-nya tergantung urutan cron malam itu.
    """

    def test_field_kosong_diisi_siapa_pun(self):
        updates, sources = resolve_updates({}, DataSource.ESPN, {'goals': 2})
        self.assertEqual(updates, {'goals': 2})
        self.assertEqual(sources['goals'], DataSource.ESPN)

    def test_sumber_prioritas_lebih_tinggi_menimpa(self):
        existing = {'goals': DataSource.ESPN}
        updates, sources = resolve_updates(existing, DataSource.FOTMOB, {'goals': 3})
        self.assertEqual(updates, {'goals': 3})
        self.assertEqual(sources['goals'], DataSource.FOTMOB)

    def test_sumber_prioritas_lebih_rendah_ditolak(self):
        """Ini inti masalahnya: urutan cron nggak boleh mengubah isi database."""
        existing = {'goals': DataSource.FOTMOB}
        updates, sources = resolve_updates(existing, DataSource.ESPN, {'goals': 99})
        self.assertEqual(updates, {})
        self.assertEqual(sources['goals'], DataSource.FOTMOB)

    def test_xg_dipegang_understat_walau_fotmob_lebih_tinggi_secara_umum(self):
        """Semua turunan xG diambil dari satu model yang sama biar konsisten."""
        existing = {'xg': DataSource.UNDERSTAT}
        updates, _ = resolve_updates(existing, DataSource.FOTMOB, {'xg': 1.2})
        self.assertEqual(updates, {})

        # Sebaliknya, Understat boleh menimpa xG yang ditulis FotMob.
        updates, sources = resolve_updates({'xg': DataSource.FOTMOB},
                                           DataSource.UNDERSTAT, {'xg': 1.66})
        self.assertEqual(updates, {'xg': 1.66})
        self.assertEqual(sources['xg'], DataSource.UNDERSTAT)

    def test_nilai_none_nggak_pernah_ditulis(self):
        """Provider sering ngirim field kosong — itu nggak boleh menghapus
        nilai yang sudah ada, dan nggak boleh ngeklaim sumber."""
        updates, sources = resolve_updates({}, DataSource.FOTMOB, {'goals': None})
        self.assertEqual(updates, {})
        self.assertNotIn('goals', sources)

    def test_sumber_tak_dikenal_cuma_boleh_isi_yang_kosong(self):
        updates, _ = resolve_updates({}, 'provider_baru', {'goals': 1})
        self.assertEqual(updates, {'goals': 1})
        updates, _ = resolve_updates({'goals': DataSource.ESPN}, 'provider_baru', {'goals': 9})
        self.assertEqual(updates, {})

    def test_beberapa_field_sekaligus_dinilai_sendiri_sendiri(self):
        existing = {'xg': DataSource.UNDERSTAT, 'touches': DataSource.ESPN}
        updates, sources = resolve_updates(
            existing, DataSource.FOTMOB, {'xg': 1.2, 'touches': 65, 'rating': 7.5}
        )
        self.assertNotIn('xg', updates)          # Understat menang
        self.assertEqual(updates['touches'], 65)  # FotMob menang atas ESPN
        self.assertEqual(updates['rating'], 7.5)  # field kosong
        self.assertEqual(sources['xg'], DataSource.UNDERSTAT)


class DescribeSourcesTests(SimpleTestCase):
    """Label chip 'sumber: ...' di kartu."""

    def test_gabungan_beberapa_sumber(self):
        fs = {'xg': DataSource.UNDERSTAT, 'touches': DataSource.FOTMOB}
        self.assertEqual(describe_sources(fs, ['xg', 'touches']), 'FotMob + Understat')

    def test_urutannya_stabil_apa_pun_urutan_field_diminta(self):
        fs = {'xg': DataSource.UNDERSTAT, 'touches': DataSource.FOTMOB}
        self.assertEqual(
            describe_sources(fs, ['xg', 'touches']),
            describe_sources(fs, ['touches', 'xg']),
        )

    def test_field_tanpa_sumber_diabaikan(self):
        fs = {'xg': DataSource.UNDERSTAT}
        self.assertEqual(describe_sources(fs, ['xg', 'belum_ada']), 'Understat')

    def test_kosong_berarti_kosong(self):
        self.assertEqual(describe_sources({}, ['xg']), '')
        self.assertEqual(describe_sources(None, ['xg']), '')
