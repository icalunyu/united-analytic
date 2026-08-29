"""Generator Prompt — PS-05.

Alasan kartu ini ada, dari handoff: user **tidak ingin app membuat gambar**.
App menghasilkan prompt siap tempel ke alat AI mana pun, di mana teks dan
angkanya berasal dari data kita sehingga AI cuma mengerjakan visualnya.

Urutan blok dipertahankan persis seperti spesifikasi, karena urutan itu yang
menentukan apa yang dibaca duluan oleh model yang menerimanya:

    perintah + dimensi → GAYA VISUAL → ATURAN TEKS → LAGA
    → DATA YANG BOLEH DIPAKAI → ISI TIAP SLIDE → FOOTER

**ATURAN TEKS ditaruh sebelum datanya, bukan sesudah.** Ini bukan detail
kosmetik. Instruksi "jangan bulatkan angka" yang datang setelah angkanya
sudah dibaca jauh lebih sering diabaikan daripada yang datang sebelumnya.

Semua angka disalin apa adanya dari kartu yang menghasilkannya. Tidak ada
pemformatan ulang di modul ini — begitu prompt memformat ulang sebuah angka,
angka di konten bisa berbeda dari angka di app, dan itu persis kesalahan yang
kartu ini seharusnya cegah.

**Dua penyimpangan dari handoff, keduanya atas permintaan user.**

1. Handoff menyuruh GAYA VISUAL memuat *"larangan foto pemain dan lambang
   klub"*. Larangan itu dicabut: alur kerjanya sekarang user melampirkan foto
   laga sendiri bersama prompt ini, dan slide berisi teks saja dinilai terlalu
   kering. Yang tersisa cuma arahan supaya foto lampiran itu yang dipakai —
   bukan wajah yang dikarang model, karena hasilnya tidak pernah mirip.

2. Handoff menyuruh ATURAN TEKS memaksa bahasa Indonesia. Sekarang campuran
   diizinkan untuk istilah yang memang hidup dalam bahasa Inggris (xG, clean
   sheet, matchday). Menerjemahkan paksa istilah teknis bikin pembacanya
   berhenti — persis yang terjadi pada "simpangan baku", yang sekarang ditulis
   "standard deviation".
"""

from matches import scoreline

# Token warna dari design handoff. Ditulis di prompt supaya konten yang
# dihasilkan alat luar tetap satu keluarga dengan tampilan app.
PALET = {
    'latar': '#0A0B0D',
    'permukaan': '#121317',
    'teks': '#E8E9EB',
    'teks_redup': '#868C96',
    'aksen': '#D6263A',
    'positif': '#00C271',
    'peringatan': '#E4B84A',
}

TIPE = {
    'feed': {
        'label': 'Feed tunggal',
        'dimensi': '1:1, 1080×1080 px',
        'perintah': 'Buat satu gambar feed Instagram',
        'format': [
            'Satu gambar saja.',
            'Satu angka utama berukuran besar, satu kalimat pendukung, satu baris konteks.',
        ],
    },
    'carousel': {
        'label': 'Carousel',
        'dimensi': '4:5, 1080×1350 px, 4 slide',
        'perintah': 'Buat carousel Instagram 4 slide',
        'format': [
            'Slide 1: judul laga + skor. Tidak ada angka lain di slide ini.',
            'Slide 2–3: satu angka besar per slide dengan kalimat penjelasnya.',
            'Slide 4: penutup berisi sumber data.',
        ],
    },
    'reels': {
        'label': 'Video / Reels',
        'dimensi': '9:16, 1080×1920 px',
        'perintah': 'Tulis naskah video pendek beserta arahan visual per adegan',
        'format': [
            'Empat adegan, masing-masing 3–5 detik.',
            'Tiap adegan: satu baris naskah yang dibacakan + satu baris arahan visual.',
            'Angka muncul sebagai teks di layar, bukan hanya diucapkan.',
        ],
    },
    'thread': {
        'label': 'Thread di X',
        'dimensi': 'teks, tanpa gambar',
        'perintah': 'Tulis satu thread di X',
        'format': [
            'Satu tweet pembuka berisi hasil dan skor.',
            'Satu angka per tweet — jangan menumpuk dua angka dalam satu tweet.',
            'Tweet penutup menyebut sumber data.',
            'Maksimal 280 karakter per tweet.',
        ],
    },
    'story': {
        'label': 'Story',
        'dimensi': '9:16, 1080×1920 px',
        'perintah': 'Buat satu story Instagram',
        'format': [
            'Satu gambar vertikal.',
            'Satu angka besar di tengah, satu kalimat di bawahnya.',
            'Sisakan 250 px kosong di atas dan bawah supaya tidak tertutup UI Instagram.',
        ],
    },
}

SUMBER = {
    'moments': 'Saved moments',
    'sistem': 'Analisis sistem',
    'gabungan': 'Gabungan',
}

NADA = {
    'analis': (
        'Nada analis: tenang, tanpa tanda seru, tanpa kata sifat berlebihan. '
        'Sebut angka lebih dulu, baru artinya.'
    ),
    'siaran': (
        'Nada siaran: kalimat pendek yang enak dibacakan, boleh satu kalimat '
        'pembuka yang mengundang, tetap tanpa melebih-lebihkan.'
    ),
    'socmed': (
        'Nada socmed: ringkas, akrab, boleh satu emoji di akhir. Tetap tidak '
        'boleh menambah klaim yang tidak ada di data.'
    ),
}


def _baris_data(momen, angka, nilai_pemain, sumber):
    """Daftar fakta yang boleh dipakai, apa adanya."""
    baris = []
    teks_momen = ''

    if sumber in ('moments', 'gabungan'):
        for m in momen:
            menit = f"{m.minute}' " if m.minute is not None else ''
            angka_teks = f' [{m.figure}]' if m.figure else ''
            baris.append(f'- {menit}{m.text}{angka_teks}')
        teks_momen = ' '.join(m.text for m in momen)

    if sumber in ('sistem', 'gabungan'):
        for a in angka:
            # Rata, tanpa kurung bersarang. Versi lama membungkus kalimat yang
            # sudah berkurung jadi `(rata-rata musim 4,7, jauh di bawah
            # kebiasaan (1,4 standard deviation))` — benar, tapi tidak terbaca.
            baris.append(
                f'- {a["label"]}: {a["nilai_teks"]} — {a["simpangan_kata"]} '
                f'({a["pembanding"]} · {a["sd_teks"]} standard deviation)'
            )
        for r in nilai_pemain[:3]:
            if r['nilai'] is None:
                continue
            # Detektor PS-04 juga menghasilkan momen "X dinilai 9,0". Kalau
            # sumbernya 'gabungan', fakta yang sama masuk dua kali dengan
            # kalimat berbeda — dan model yang menerimanya bakal menganggapnya
            # dua bahan terpisah lalu memakai dua-duanya.
            if r['player'].name in teks_momen:
                continue
            ekor = f' — {", ".join(r["kontribusi"])}' if r['kontribusi'] else ''
            baris.append(f'- Nilai {r["player"].name}: {r["teks"]}{ekor}')
    return baris


def susun(match, momen, angka, nilai_pemain, tipe='carousel', sumber='gabungan'):
    """Prompt lengkap sebagai satu blok teks."""
    spek = TIPE.get(tipe, TIPE['carousel'])
    ident = scoreline.judul_laga(match)
    tanggal = match.kickoff_at.strftime('%d %B %Y') if match.kickoff_at else ''

    data = _baris_data(momen, angka, nilai_pemain, sumber)

    bagian = []
    bagian.append(f'{spek["perintah"]}. Ukuran {spek["dimensi"]}.')
    bagian.append('')

    bagian.append('GAYA VISUAL')
    bagian.append(f'- Latar {PALET["latar"]}, kartu {PALET["permukaan"]}, teks {PALET["teks"]}.')
    bagian.append(f'- Aksen merah {PALET["aksen"]} hanya untuk satu elemen per slide.')
    bagian.append(
        '- Tipografi: judul huruf kapital tebal berkarakter condensed; '
        'semua ANGKA memakai font monospace.'
    )
    bagian.append(
        '- Foto laga dilampirkan bersama prompt ini. Pakai foto itu sebagai '
        'dasar visualnya, dan JANGAN mengarang wajah pemain secara generatif — '
        'wajah buatan tidak pernah mirip dan langsung ketahuan.'
    )
    bagian.append(
        '- Kalau tidak ada foto yang dilampirkan, pakai komposisi grafis saja.'
    )
    bagian.append(
        '- Teks harus tetap terbaca di atas foto: beri lapisan gelap transparan '
        'atau taruh teks di area foto yang paling kosong.'
    )
    bagian.append('- Banyak ruang kosong. Satu gagasan per slide.')
    bagian.append('')

    bagian.append('ATURAN TEKS')
    bagian.append('- Tulis teks PERSIS seperti yang tertulis di bagian DATA di bawah.')
    bagian.append('- JANGAN mengubah, membulatkan, menyingkat, atau menghitung ulang angka.')
    bagian.append(
        '- Bahasa Indonesia, boleh dicampur istilah Inggris yang memang lazim '
        'dipakai orang sepak bola (xG, clean sheet, matchday, standard '
        'deviation, big chance). JANGAN memaksa menerjemahkannya — istilah '
        'yang diterjemahkan setengah-setengah justru bikin pembaca berhenti.'
    )
    bagian.append('- JANGAN menambah kalimat, klaim, atau angka yang tidak ada di bagian DATA.')
    bagian.append('- Kalau sebuah slide kekurangan bahan, biarkan lebih kosong — jangan diisi karangan.')
    bagian.append('')

    bagian.append('LAGA')
    bagian.append(f'- {ident}')
    if match.league_name:
        bagian.append(f'- Kompetisi: {match.league_name}')
    if tanggal:
        bagian.append(f'- Tanggal: {tanggal}')
    if match.venue:
        bagian.append(f'- Stadion: {match.venue}')
    bagian.append('')

    bagian.append('DATA YANG BOLEH DIPAKAI')
    bagian.extend(data or ['- (belum ada fakta tercentang — jangan mengarang apa pun)'])
    bagian.append('')

    bagian.append('ISI TIAP SLIDE')
    bagian.extend(f'- {b}' for b in spek['format'])
    bagian.append('')

    bagian.append('FOOTER')
    bagian.append('- Tulis kecil di bawah: "MU Analytics · IndoManUtd Jogja"')
    bagian.append('- Sertakan tanggal laga.')

    return '\n'.join(bagian)


def caption(match, momen, angka, nada='analis'):
    """Draf caption di bawah kotak prompt. Sengaja pendek dan tanpa hashtag —
    hashtag itu keputusan tim socmed, bukan keputusan data."""
    ident = scoreline.judul_laga(match)
    baris = [ident]
    fakta = None
    if momen:
        fakta = momen[0].text
    elif angka:
        a = angka[0]
        fakta = f'{a["label"]} {a["nilai_teks"]} — {a["pembanding"]}.'
    if fakta:
        baris.append(fakta)
    baris.append(NADA.get(nada, NADA['analis']))
    return '\n\n'.join(baris)
