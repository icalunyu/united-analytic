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
