"""Daftar umpan berita + parser RSS/Atom minimal.

Semua sumber di sini sudah **diuji hidup** dan dinilai sah dipakai. Dua yang
sengaja TIDAK ada, dan alasannya bukan teknis:

- **The Athletic** — robots.txt-nya (teks baku New York Times) melarang
  eksplisit *"creating or providing archived or cached data sets containing our
  content"*. Tabel `NewsItem` ini persis itu. Konsekuensinya David Ornstein
  nggak punya jalur sah sama sekali, karena dia cuma menulis di sana. Yang bisa
  kita lakukan: menangkap outlet lain yang MENGUTIP dia, dan mencatat namanya
  di `quoted_source`.
- **BBC Sport** — Terms of Use pasal 15 melarang *"pluck metadata from our
  content or RSS feeds"*. Yang BBC izinkan cuma menampilkan feed apa adanya
  tanpa diubah. Menyimpannya ke Postgres lalu memakainya buat mesin
  "N sumber sepakat" persis definisi yang mereka larang.

Jangan menambahkan keduanya kembali "karena feed-nya jalan". Feed-nya memang
jalan; yang melarang bukan servernya, tapi syaratnya.
"""

import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

# (nama penerbit, grup kepemilikan, tier, url)
#
# `grup` yang dipakai menghitung kesepakatan, BUKAN nama penerbit. Reach plc
# memiliki MEN, Mirror, Express, dan Daily Star — menghitungnya sebagai empat
# sumber independen bikin angka konsensus bohong.
FEEDS = [
    ('Manchester United', 'Man Utd', 'A',
     'https://www.youtube.com/feeds/videos.xml?channel_id=UC6yW44UGJJBvYTlfC7CRg2Q'),
    ('Sky Sports', 'Sky', 'B', 'https://www.skysports.com/rss/11667'),
    ('The Guardian', 'Guardian Media Group', 'B',
     'https://www.theguardian.com/football/manchester-united/rss'),
    ('Manchester Evening News', 'Reach plc', 'B',
     'https://www.manchestereveningnews.co.uk/all-about/manchester-united-fc/?service=rss'),
    ('The Independent', 'Independent', 'B',
     'https://www.independent.co.uk/topic/manchester-united/rss'),
    ('Fabrizio Romano', 'Fabrizio Romano', 'C',
     'https://www.youtube.com/feeds/videos.xml?channel_id=UCX1em-uaFMS02Rrk_Bowyng'),
    ('The Peoples Person', 'The Peoples Person', 'C',
     'https://thepeoplesperson.com/feed/'),
    ('United In Focus', 'United In Focus', 'C', 'https://unitedinfocus.com/feed/'),
]

# Nama wartawan yang sering dikutip. Dipakai membedakan "6 outlet punya reporter
# sendiri" dari "6 outlet mengutip 1 orang" — dua hal yang sangat berbeda tapi
# sama-sama terbaca "6 sumber sepakat" kalau nggak dibedakan.
DIKUTIP = ('Romano', 'Ornstein', 'Sheth', 'Jacobs', 'Bailey')

_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'dc': 'http://purl.org/dc/elements/1.1/',
}

# Kata kunci penyaring: feed umum (Metro, talkSPORT) memuat cabang lain.
KATA_MU = ('manchester united', 'man utd', 'man united', 'united', 'old trafford')


def _teks(elem, *paths):
    for path in paths:
        found = elem.find(path, _NS)
        if found is not None and (found.text or '').strip():
            return found.text.strip()
    return ''


def _waktu(teks):
    """Parse pubDate RSS atau updated Atom.

    Sky menulis zona waktu sebagai singkatan: 'Sun, 23 Aug 2026 20:19:00 BST'.
    `parsedate_to_datetime` mengembalikan datetime NAIVE untuk itu — dan kalau
    hasilnya diperlakukan sebagai UTC, seluruh waktu terbit Sky meleset 1 jam
    sepanjang musim panas, bikin urutan kronologis lintas-sumber kacau.
    """
    from datetime import timedelta, timezone as dt_tz

    if not teks:
        return None
    teks = teks.strip()

    singkatan = {'BST': 1, 'GMT': 0, 'UTC': 0, 'CET': 1, 'CEST': 2}
    akhir = teks.rsplit(' ', 1)[-1].upper()
    offset = singkatan.get(akhir)

    try:
        waktu = parsedate_to_datetime(teks)
    except (TypeError, ValueError):
        try:
            from datetime import datetime

            waktu = datetime.fromisoformat(teks.replace('Z', '+00:00'))
        except ValueError:
            return None

    if waktu.tzinfo is None:
        if offset is None:
            return None  # zona nggak diketahui — lebih baik kosong daripada salah
        waktu = waktu.replace(tzinfo=dt_tz(timedelta(hours=offset)))
    return waktu.astimezone(dt_tz.utc)


def dikutip_siapa(judul):
    """Nama wartawan yang disebut di judul, kalau ada."""
    for nama in DIKUTIP:
        if re.search(rf'\b{nama}\b', judul, re.I):
            return nama
    return ''


def tentang_mu(judul):
    teks = (judul or '').lower()
    return any(k in teks for k in KATA_MU)


def parse(xml_bytes):
    """Item dari satu feed RSS atau Atom.

    Cuma empat elemen yang dibaca: judul, tautan, waktu, penulis. Elemen lain
    — terutama `content:encoded` yang berisi artikel utuh — nggak pernah
    disentuh, jadi nggak ada jalan buat isinya masuk DB nggak sengaja.
    """
    try:
        akar = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []

    hasil = []

    # RSS 2.0
    for item in akar.iter('item'):
        judul = _teks(item, 'title')
        tautan = _teks(item, 'link')
        if not judul or not tautan:
            continue
        hasil.append({
            'title': judul,
            'url': tautan,
            'published_at': _waktu(_teks(item, 'pubDate')),
            'author': _teks(item, 'author', 'dc:creator'),
        })

    # Atom (YouTube)
    for entry in akar.iter(f'{{{_NS["atom"]}}}entry'):
        judul = _teks(entry, 'atom:title')
        tautan_el = entry.find('atom:link', _NS)
        tautan = tautan_el.get('href') if tautan_el is not None else ''
        if not judul or not tautan:
            continue
        penulis = entry.find('atom:author/atom:name', _NS)
        hasil.append({
            'title': judul,
            'url': tautan,
            'published_at': _waktu(_teks(entry, 'atom:published', 'atom:updated')),
            'author': (penulis.text or '').strip() if penulis is not None else '',
        })

    return hasil


# Kata yang berhuruf kapital tapi bukan nama orang — dibuang sebelum
# mengelompokkan topik.
_BUKAN_NAMA = {
    'Man', 'Utd', 'United', 'Manchester', 'The', 'A', 'An', 'In', 'On', 'At',
    'To', 'For', 'And', 'Of', 'With', 'From', 'By', 'As', 'Is', 'Are', 'Was',
    'Premier', 'League', 'Cup', 'FC', 'LIVE', 'BREAKING', 'Transfer', 'News',
    'Old', 'Trafford', 'Red', 'Devils', 'Sir', 'City', 'Hull', 'Ipswich',
    'Chelsea', 'Arsenal', 'Liverpool', 'Everton', 'Leeds', 'Tottenham',
}


def nama_di_judul(judul):
    """Nama berhuruf kapital yang muncul di judul, buat mengelompokkan topik.

    Sengaja sederhana dan transparan. Mencocokkan judul lintas penerbit secara
    semantik itu masalah yang gampang menghasilkan sampah kalau dipaksakan —
    dan sampah di panel "N sumber sepakat" lebih berbahaya daripada panel
    kosong, karena angkanya kelihatan meyakinkan.

    Yang dilakukan cuma: ambil kata berhuruf kapital yang bukan kata umum.
    Kalau dua penerbit dari GRUP BERBEDA sama-sama menyebut nama yang sama
    dalam jendela waktu yang sama, itu sinyal yang layak ditampilkan — dengan
    keterangan bahwa begitulah cara menghitungnya.
    """
    kata = re.findall(r'\b[A-Z][a-zà-ÿA-Z\'’-]{2,}\b', judul or '')
    return {k for k in kata if k not in _BUKAN_NAMA}
