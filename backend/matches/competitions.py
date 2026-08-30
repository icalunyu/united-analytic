"""Pengelompokan `Match.league_name` yang mentah jadi kategori yang kepakai.

Nama liga di DB itu apa adanya dari provider, dan bentuknya beda-beda: ESPN
nulis '2023-24 English Premier League', Premier League API nulis 'Premier
League' polos, Highlightly nulis 'Friendlies Clubs'. Di produksi ada **44 nama
unik** buat 470 laga MU — kalau dijadiin dropdown mentah-mentah, isinya 44
baris dan nggak ada yang mau pakai.

Ini SENGAJA bukan model `Competition` beneran. Model itu pekerjaan tersendiri
(butuh migrasi, pemetaan id lintas provider, dan penggabungan laga ganda), dan
halaman Jadwal nggak perlu nunggu itu cuma buat punya filter. Fungsi murni di
sini gampang dites dan gampang dibuang kalau modelnya nanti jadi.
"""

# Urutan penting: dicek dari atas ke bawah, yang pertama cocok yang menang.
#
# 'Community Shield' harus sebelum aturan piala lain karena namanya di ESPN
# '2024 English FA Community Shield' — mengandung 'FA' tapi bukan FA Cup.
_RULES = (
    ('eropa', ('uefa champions league', 'uefa europa league', 'uefa europa conference',
               'uefa super cup')),
    ('persahabatan', ('club friendly', 'club friendlies', 'friendlies clubs',
                      'friendly', 'summer series')),
    ('piala', ('community shield', 'fa cup', 'carabao cup', 'league cup',
               'efl cup')),
    ('liga', ('premier league',)),
)

LABELS = {
    'liga': 'Liga',
    'piala': 'Piala domestik',
    'eropa': 'Eropa',
    'persahabatan': 'Persahabatan',
    'lainnya': 'Lainnya',
}

# Urutan tampil di UI, dari yang paling sering dilihat.
ORDER = ('liga', 'eropa', 'piala', 'persahabatan', 'lainnya')


# Nama liga -> slug kompetisi ESPN. Urutannya dibaca dari atas ke bawah, sama
# seperti `_RULES`, dan alasannya sama: 'Premier League - Summer Series' memuat
# 'premier league' tapi itu laga pramusim, bukan liga.
#
# Dipakai mode live buat menembak SATU kompetisi saja. Penarikan biasa
# menyapu delapan slug dan makan ~9 detik; kalau itu dijalankan tiap dua menit
# selama laga, kita menembak ESPN 240 kali per jam untuk tujuh kompetisi yang
# jelas-jelas tidak sedang bermain.
_SLUG_RULES = (
    ('club.friendly', ('club friendly', 'club friendlies', 'friendlies clubs',
                       'friendly', 'summer series')),
    ('eng.charity', ('community shield', 'charity shield')),
    ('uefa.champions', ('uefa champions league',)),
    ('uefa.europa.conf', ('uefa europa conference', 'conference league')),
    ('uefa.europa', ('uefa europa league',)),
    ('eng.fa', ('fa cup',)),
    ('eng.league_cup', ('carabao cup', 'league cup', 'efl cup')),
    ('eng.1', ('premier league',)),
)


def espn_slug(league_name):
    """Slug ESPN buat satu nama liga mentah, atau None kalau tidak dikenal.

    None itu jawaban yang sah dan harus ditangani pemanggilnya — provider bisa
    menambah kompetisi kapan saja. Menebak slug buat nama yang tidak dikenal
    menghasilkan panggilan yang pasti gagal, dan mode live jadi diam tanpa
    gejala.
    """
    teks = (league_name or '').lower()
    for slug, kata_kunci in _SLUG_RULES:
        if any(k in teks for k in kata_kunci):
            return slug
    return None


def classify(league_name):
    """Kembalikan kunci kategori buat satu nama liga mentah.

    Nama yang nggak dikenal masuk 'lainnya' — bukan dibuang. Provider bisa
    nambah kompetisi kapan aja (mis. Piala Dunia Antarklub), dan laga yang
    nggak kekategori lebih baik kelihatan di bawah label jujur daripada hilang
    dari halaman tanpa jejak.
    """
    teks = (league_name or '').lower()
    for kunci, kata_kunci in _RULES:
        if any(k in teks for k in kata_kunci):
            return kunci
    return 'lainnya'


def league_names_for(kategori):
    """Nama-nama liga mentah yang masuk satu kategori, dibaca dari DB.

    Dipakai buat nyaring queryset: karena `classify` jalan di Python dan bukan
    di SQL, penyaringannya dilakukan dengan `league_name__in` dari daftar ini.
    """
    from matches.models import Match

    semua = (
        Match.objects.order_by()  # WAJIB: tanpa ini GROUP BY ikut nyeret
        .values_list('league_name', flat=True)  # kickoff_at dan hasilnya 288
        .distinct()                             # baris, bukan 44
    )
    return [nama for nama in semua if classify(nama) == kategori]
