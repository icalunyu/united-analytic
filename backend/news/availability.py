"""Menurunkan status ketersediaan pemain dari JUDUL berita.

Ini sumber ketersediaan kedua, dan alasan panel Konflik Sumber (SQ-01) punya
bahan buat dikerjakan. Sebelum ini cuma FPL yang menulis `PlayerAvailability`,
dan satu sumber tidak bisa berselisih dengan siapa pun.

**Batas yang disengaja, dan kenapa.**

Yang dibaca cuma judul — isi artikel tidak pernah kita simpan (lihat
`news/models.py`), jadi tidak ada yang lain buat dibaca. Judul itu sinyal
lemah: "Bruno Fernandes injury latest" tidak bilang apa-apa soal statusnya.
Karena itu polanya sengaja sempit dan hasilnya **tidak pernah dipakai diam-
diam**: dia masuk sebagai satu sumber di antara sumber lain, dan begitu dia
berbeda dari FPL, keputusannya diserahkan ke analis lewat SQ-01. Itu justru
gunanya — bukan menebak, tapi memunculkan pertanyaan.

Yang TIDAK dilakukan: menaikkan status jadi bugar dari judul. Judul "Player X
back in training" muncul jauh lebih sering daripada pemainnya benar-benar
siap main, dan salah ke arah "bugar" jauh lebih berbahaya daripada salah ke
arah "diragukan" — yang pertama bikin nama masuk prediksi susunan, yang kedua
cuma bikin dia ditanyakan.
"""

import re
from datetime import timedelta

from players.models import PlayerAvailability

Status = PlayerAvailability.Status

# Urutan penting: pola pertama yang cocok yang dipakai. Skorsing didahulukan
# karena "banned for three games" juga mengandung kata yang mirip absen.
POLA = (
    (
        Status.SUSPENDED,
        re.compile(
            r'\b(suspended|suspension|banned for|serves? (?:a )?ban|match ban)\b', re.I
        ),
    ),
    (
        Status.OUT,
        re.compile(
            r'\b(ruled out|out for (?:the|\d|several|a few|weeks|months)'
            r'|sidelined|will miss|to miss\b|out until'
            r'|face[sd]? (?:weeks|months) out'
            r'|undergo(?:es|ne)? surgery|surgery ruled)\b',
            re.I,
        ),
    ),
    (
        Status.DOUBTFUL,
        re.compile(
            r'\b(doubtful|a doubt|injury doubt|major doubt|fitness doubt'
            r'|race to be fit|racing to be fit|fitness test|touch and go'
            r'|could miss|may miss|might miss|injury scare|limps? off'
            r'|forced off|withdrawn injured)\b',
            re.I,
        ),
    ),
)

# Judul yang mengandung ini tidak pernah dipakai walau polanya cocok.
# "Rumour", "linked", dan sejenisnya biasanya soal pemain klub lain; kalimat
# tanya biasanya spekulasi, bukan kabar.
PENOLAK = re.compile(
    r'\b(rumou?r|linked with|transfer|could sign|set to sign|target|bid for'
    r'|preview|predicted (?:xi|line-?up)|quiz|opinion|column)\b',
    re.I,
)

# Berita lebih tua dari ini tidak lagi dianggap menggambarkan keadaan
# sekarang. Status cedera bergerak cepat; judul dua minggu lalu bukan kabar,
# itu arsip.
UMUR_MAKS = timedelta(days=10)

# Nama sependek ini terlalu sering muncul sebagai kata biasa di judul Inggris.
PANJANG_NAMA_MINIMUM = 4


def nama_pencocok(player):
    """Bentuk nama yang boleh dicari di judul.

    Cuma nama belakang (dan nama lengkap), bukan nama depan — judul berbahasa
    Inggris menyebut pemain dengan nama belakang, dan nama depan seperti
    'Mason' atau 'Harry' terlalu sering menunjuk orang lain.
    """
    penuh = (player.name or '').strip()
    if not penuh:
        return []
    bagian = penuh.split()
    calon = [penuh]
    belakang = bagian[-1]
    if len(belakang) >= PANJANG_NAMA_MINIMUM:
        calon.append(belakang)
    # Nama majemuk seperti 'Mainoo' vs 'Kobbie Mainoo' sudah tercakup; nama
    # dengan partikel ('De Ligt') diambil dua kata terakhir juga.
    if len(bagian) >= 3:
        calon.append(' '.join(bagian[-2:]))
    return calon


def cocok_nama(judul, player):
    for nama in nama_pencocok(player):
        if re.search(rf'\b{re.escape(nama)}\b', judul or '', re.I):
            return nama
    return None


def baca_status(judul):
    """Status yang diklaim judul, atau None kalau judulnya tidak mengklaim apa-apa."""
    if not judul or PENOLAK.search(judul):
        return None
    for status, pola in POLA:
        if pola.search(judul):
            return status
    return None


def pemain_disebut(judul, pemain):
    """Pemain MU yang namanya muncul di judul."""
    return [p for p in pemain if cocok_nama(judul, p) is not None]


def temuan(berita, pemain, sekarang):
    """[(player, status, item)] — satu temuan per pemain, yang paling baru menang.

    Fungsi murni supaya bisa dites tanpa DB dan tanpa jaringan.

    **Judul harus menyebut TEPAT SATU pemain MU.** Ini bukan kehati-hatian
    berlebihan, ini menutup lubang yang nyata. Genre judul sepak bola Inggris
    didominasi rangkuman: *"Amad, Mount, Baleba — Man United injury news and
    return dates"*, *"Five Man Utd stars to miss Ipswich clash"*. Tanpa aturan
    ini, satu judul rangkuman menandai SEMUA nama yang kebetulan disebut
    dengan status yang sama — padahal isinya justru menjelaskan bahwa nasib
    mereka berbeda-beda.

    Diperiksa di 484 berita produksi: 37 judul menyebut kata cedera, dan tidak
    satu pun mengklaim status satu pemain secara utuh. Jadi aturan ini memang
    menutup lubang yang akan sering kena, bukan kasus langka.
    """
    batas = sekarang - UMUR_MAKS
    hasil = {}
    for item in berita:
        terbit = item.published_at
        if terbit is None or terbit < batas:
            continue
        status = baca_status(item.title)
        if status is None:
            continue
        disebut = pemain_disebut(item.title, pemain)
        if len(disebut) != 1:
            continue
        p = disebut[0]
        lama = hasil.get(p.pk)
        if lama is None or terbit > lama[2].published_at:
            hasil[p.pk] = (p, status, item)
    return sorted(hasil.values(), key=lambda t: t[0].name)


def simpan(temuan_list, sekarang):
    """Tulis hasil ke PlayerAvailability. Return jumlah baris tersentuh."""
    from players.models import DataSource

    n = 0
    for player, status, item in temuan_list:
        PlayerAvailability.objects.update_or_create(
            player=player,
            source=DataSource.NEWS,
            defaults={
                'status': status,
                # Judul apa adanya + penerbitnya. Analis harus bisa menilai
                # sendiri apakah judulnya benar-benar berarti itu.
                'note': f'{item.publisher}: {item.title}'[:255],
                'chance_pct': None,
                'source_updated_at': item.published_at,
            },
        )
        n += 1
    return n


def bersihkan(sekarang, kecuali_ids):
    """Hapus turunan berita yang judulnya sudah kedaluwarsa.

    Tanpa ini, satu judul "ruled out" dari bulan lalu menempel selamanya dan
    diam-diam terus berselisih dengan FPL — konflik palsu yang tidak pernah
    selesai karena tidak ada yang menyegarkannya.
    """
    from players.models import DataSource

    hapus = PlayerAvailability.objects.filter(source=DataSource.NEWS).exclude(
        player_id__in=kecuali_ids
    )
    jumlah = hapus.count()
    hapus.delete()
    return jumlah
