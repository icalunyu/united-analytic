"""Test pipeline berita.

Yang paling penting dijaga di sini bukan "parsernya jalan", tapi tiga hal yang
kalau salah bikin angkanya BOHONG sambil kelihatan meyakinkan.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from news.feeds import dikutip_siapa, nama_di_judul, parse, tentang_mu, _waktu
from news.models import NewsItem


class ParserFeedTests(SimpleTestCase):
    def test_rss_dibaca(self):
        xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Man Utd sign striker</title>
        <link>https://x.test/a</link>
        <pubDate>Sun, 23 Aug 2026 20:19:00 BST</pubDate>
        <author>Wartawan A</author></item></channel></rss>"""
        item = parse(xml)
        self.assertEqual(len(item), 1)
        self.assertEqual(item[0]['title'], 'Man Utd sign striker')
        self.assertEqual(item[0]['author'], 'Wartawan A')

    def test_isi_artikel_TIDAK_ikut_terbaca(self):
        """Feed WordPress mengirim artikel UTUH di content:encoded. Parser
        cuma membaca elemen yang disebut eksplisit, jadi isinya nggak punya
        jalan masuk ke DB — bahkan nggak sengaja."""
        xml = b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><item>
        <title>Man Utd news</title><link>https://x.test/b</link>
        <content:encoded>ISI ARTIKEL BERHAK CIPTA YANG PANJANG</content:encoded>
        </item></channel></rss>"""
        item = parse(xml)
        self.assertEqual(set(item[0]), {'title', 'url', 'published_at', 'author'})
        self.assertNotIn('ISI ARTIKEL', str(item))

    def test_atom_youtube_dibaca(self):
        xml = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>United highlights</title>
        <link rel="alternate" href="https://youtube.test/v"/>
        <published>2026-08-23T20:19:00+00:00</published>
        <author><name>Manchester United</name></author></entry></feed>"""
        item = parse(xml)
        self.assertEqual(item[0]['url'], 'https://youtube.test/v')
        self.assertEqual(item[0]['author'], 'Manchester United')

    def test_xml_rusak_nggak_bikin_error(self):
        self.assertEqual(parse(b'<rss><broken'), [])

    def test_zona_waktu_singkatan_BST(self):
        """Sky menulis 'BST', dan parsedate_to_datetime mengembalikan datetime
        NAIVE untuk itu. Kalau dianggap UTC, seluruh waktu terbit Sky meleset
        1 jam sepanjang musim panas dan urutan lintas-sumber jadi kacau."""
        w = _waktu('Sun, 23 Aug 2026 20:19:00 BST')
        self.assertEqual(w.hour, 19, 'BST itu UTC+1')
        self.assertEqual(_waktu('Sun, 23 Aug 2026 20:19:00 GMT').hour, 20)

    def test_zona_tak_dikenal_dikosongkan_bukan_ditebak(self):
        self.assertIsNone(_waktu('Sun, 23 Aug 2026 20:19:00 XYZ'))

    def test_deteksi_wartawan_yang_dikutip(self):
        self.assertEqual(dikutip_siapa('Romano: United close in'), 'Romano')
        self.assertEqual(dikutip_siapa('United win 3-0'), '')

    def test_penyaring_tentang_mu(self):
        self.assertTrue(tentang_mu('Man Utd sign striker'))
        self.assertFalse(tentang_mu('Arsenal beat Chelsea'))

    def test_nama_di_judul_membuang_kata_umum(self):
        nama = nama_di_judul('Man Utd LIVE: Sesko deal close, says Romano')
        self.assertIn('Sesko', nama)
        self.assertNotIn('Man', nama)
        self.assertNotIn('United', nama)
        self.assertNotIn('LIVE', nama)


class KesepakatanTests(TestCase):
    """Menghitung kesepakatan per GRUP PENERBIT, bukan per artikel.

    Reach plc memiliki MEN, Mirror, Express, dan Daily Star. Menghitungnya
    sebagai empat sumber independen bikin "4 sumber sepakat" bohong — itu satu
    ruang redaksi menerbitkan ulang.
    """

    def _berita(self, penerbit, grup, judul, tier='B', dikutip=''):
        return NewsItem.objects.create(
            publisher=penerbit, publisher_group=grup, tier=tier,
            title=judul, url=f'https://x.test/{NewsItem.objects.count()}',
            published_at=timezone.now(), quoted_source=dikutip,
        )

    def test_satu_grup_beberapa_penerbit_dihitung_SATU(self):
        for penerbit in ('Manchester Evening News', 'Mirror', 'Express'):
            self._berita(penerbit, 'Reach plc', 'Sesko to United')
        r = self.client.get(reverse('dashboard:news'))
        sesko = [k for k in r.context['kesepakatan'] if k['nama'] == 'Sesko']
        self.assertFalse(sesko, 'satu grup nggak boleh lolos ambang 2 grup')

    def test_grup_berbeda_dihitung_terpisah(self):
        self._berita('Manchester Evening News', 'Reach plc', 'Sesko to United')
        self._berita('Sky Sports', 'Sky', 'Sesko medical booked')
        r = self.client.get(reverse('dashboard:news'))
        sesko = [k for k in r.context['kesepakatan'] if k['nama'] == 'Sesko'][0]
        self.assertEqual(sesko['jumlah_grup'], 2)
        self.assertEqual(sorted(sesko['grup']), ['Reach plc', 'Sky'])

    def test_kutipan_wartawan_yang_sama_ditandai(self):
        """Enam outlet mengutip satu orang bukan enam sumber."""
        self._berita('Sky Sports', 'Sky', 'Sesko deal — Romano', dikutip='Romano')
        self._berita('The Guardian', 'Guardian Media Group', 'Sesko latest — Romano',
                     dikutip='Romano')
        r = self.client.get(reverse('dashboard:news'))
        sesko = [k for k in r.context['kesepakatan'] if k['nama'] == 'Sesko'][0]
        self.assertEqual(sesko['dikutip'], ['Romano'])
        self.assertContains(r, 'satu sumber asli')

    def test_filter_tier(self):
        self._berita('Manchester United', 'Man Utd', 'Team news', tier='A')
        self._berita('Blog', 'Blog', 'Rumour', tier='C')
        r = self.client.get(reverse('dashboard:news'), {'tier': 'A'})
        self.assertEqual(len(r.context['item']), 1)
        self.assertEqual(r.context['item'][0].tier, 'A')

    def test_aturan_redaksi_tertulis_di_UI(self):
        """Handoff: aturan A/B/C harus disebut di UI, bukan cuma di dokumen."""
        r = self.client.get(reverse('dashboard:news'))
        self.assertContains(r, 'boleh langsung jadi konten')
        self.assertContains(r, 'harus disebut belum pasti')
        self.assertContains(r, 'tidak diangkat')

    def test_sentimen_fans_nggak_dikarang(self):
        r = self.client.get(reverse('dashboard:news'))
        self.assertContains(r, 'diisi manual')
        self.assertContains(r, "mengarang angka sentimen")
