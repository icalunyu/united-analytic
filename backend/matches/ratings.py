"""Nilai pemain dari event laga — PS-03, rumusnya dipinjam dari LV-06.

Handoff LV-06, apa adanya:

    nilai dasar 6,0 untuk semua pemain
    tambah bobot per aksi positif: gol, asis, peluang tercipta, umpan kunci,
      rebutan menang, penyelamatan
    kurangi bobot per aksi negatif: kehilangan bola di area sendiri, duel
      kalah, peluang terbuang
    bobot diskalakan per posisi supaya kiper dan penyerang tidak dinilai
      dengan patokan sama
    nilai dibulatkan satu desimal

PS-03 menambahkan: dihitung penuh 90 menit, pemain di bawah 30 menit ditandai
sampel kecil (**bukan dinaikkan**), tertinggi dan terendah ditandai.

**Kenapa ada `cukup_data`.** Sebagian besar kolom di sini bisa null, dan
seringnya memang null — tergantung sumber mana yang mengisi laga itu. Rumus
yang memperlakukan null sebagai nol menghasilkan 6,0 untuk semua orang dan
kelihatan seperti nilai sungguhan. Itu jenis kebohongan yang paling sulit
ketahuan, jadi pemain yang datanya tidak cukup dikembalikan sebagai `None`
dan halaman menuliskannya sebagai "data event tidak cukup", bukan sebagai 6,0.
"""

DASAR = 6.0
MIN_NILAI, MAKS_NILAI = 1.0, 10.0

# Menit di bawah ini = sampel kecil. Angkanya dari PS-03.
MENIT_SAMPEL_KECIL = 30

# Berapa kolom event harus terisi sebelum nilainya dianggap berarti. Tiga
# dipilih karena satu kolom saja (mis. cuma `minutes_played`) tidak
# membedakan apa pun, dan dua masih bisa terjadi dari baris yang nyaris kosong.
MIN_KOLOM_TERISI = 3

# `chances_created` dan `key_passes` adalah ANGKA YANG SAMA di data kita —
# diperiksa di seluruh baris yang punya keduanya, 55 dari 55 identik. Provider
# yang berbeda cuma menamainya berbeda. Memberi bobot ke dua-duanya berarti
# menghitung satu umpan dua kali, dan yang paling diuntungkan justru gelandang
# kreatif: Bruno Fernandes menembus langit-langit nilai 10 gara-gara ini.
#
# Jadi keduanya digabung jadi satu masukan lebih dulu. `chances_created`
# dipakai kalau ada, `key_passes` jadi cadangan — di produksi 1.104 baris cuma
# punya `key_passes`, jadi menjatuhkan salah satunya bukan pilihan.
PASANGAN_SETARA = {'chances_created': 'key_passes'}

KELOMPOK = {
    'GK': 'GK',
    'CB': 'BEK', 'RB': 'BEK', 'LB': 'BEK',
    'CDM': 'TENGAH', 'CM': 'TENGAH', 'CAM': 'TENGAH',
    'WNG': 'DEPAN', 'CF': 'DEPAN',
}

# Bobot per aksi, per kelompok posisi. Positif menaikkan, negatif menurunkan.
#
# Skalanya bukan hasil kalibrasi statistik — handoff tidak memberi angka, cuma
# daftar aksi dan perintah "diskalakan per posisi". Yang dijaga di sini adalah
# perbandingannya: gol berarti lebih banyak buat bek daripada buat penyerang,
# penyelamatan cuma berarti buat kiper, kebobolan cuma dihitung ke kiper.
BOBOT = {
    'GK': {
        'saves': 0.22,
        'goals_conceded': -0.35,
        'goals_prevented': 0.60,
        'passes_accurate': 0.004,
        'goals': 1.50,
        'assists': 0.80,
        'red_cards': -2.50,
        'yellow_cards': -0.25,
        'own_goals': -1.50,
    },
    'BEK': {
        'goals': 1.40, 'assists': 0.90,
        'chances_created': 0.20,
        'tackles': 0.12, 'interceptions': 0.12, 'clearances': 0.06,
        'blocks': 0.12, 'recoveries': 0.05,
        'duels_won': 0.07, 'duels_lost': -0.06,
        'aerial_duels_won': 0.06,
        'dribbled_past': -0.12, 'dispossessed': -0.10,
        'fouls_committed': -0.05,
        'yellow_cards': -0.30, 'red_cards': -2.50, 'own_goals': -1.50,
    },
    'TENGAH': {
        'goals': 1.20, 'assists': 0.85,
        'chances_created': 0.25,
        'passes_into_final_third': 0.04,
        'tackles': 0.10, 'interceptions': 0.10, 'recoveries': 0.05,
        'duels_won': 0.07, 'duels_lost': -0.07,
        'dribbles_succeeded': 0.10,
        'dispossessed': -0.12,
        'fouls_committed': -0.05,
        'yellow_cards': -0.30, 'red_cards': -2.50, 'own_goals': -1.50,
    },
    'DEPAN': {
        'goals': 1.00, 'assists': 0.80,
        'chances_created': 0.25,
        'shots_on_target': 0.12,
        'touches_opp_box': 0.04,
        'dribbles_succeeded': 0.12,
        'duels_won': 0.05, 'duels_lost': -0.05,
        'dispossessed': -0.10,
        'recoveries': 0.04,
        'yellow_cards': -0.30, 'red_cards': -2.50, 'own_goals': -1.50,
    },
}

# Kolom yang dihitung sebagai "ada datanya". `minutes_played` sengaja TIDAK
# masuk — hampir selalu terisi, jadi memasukkannya bikin ambang MIN_KOLOM
# lolos untuk baris yang sebenarnya kosong.
KOLOM_BUKTI = sorted({k for b in BOBOT.values() for k in b} | set(PASANGAN_SETARA.values()))

# Nama Indonesia buat kalimat kontribusi.
SEBUTAN = {
    'goals': 'gol', 'assists': 'asis', 'saves': 'penyelamatan',
    'chances_created': 'peluang tercipta', 'key_passes': 'umpan kunci',
    'tackles': 'tekel', 'interceptions': 'intersep', 'clearances': 'sapuan',
    'blocks': 'blok', 'recoveries': 'bola direbut kembali',
    'duels_won': 'duel menang', 'duels_lost': 'duel kalah',
    'aerial_duels_won': 'duel udara menang',
    'dribbles_succeeded': 'dribel sukses', 'dispossessed': 'kehilangan bola',
    'dribbled_past': 'dilewati', 'goals_conceded': 'kebobolan',
    'shots_on_target': 'tembakan tepat sasaran',
    'passes_into_final_third': 'umpan ke sepertiga akhir',
    'touches_opp_box': 'sentuhan di kotak lawan',
    'goals_prevented': 'gol dicegah',
    'yellow_cards': 'kartu kuning', 'red_cards': 'kartu merah',
    'own_goals': 'gol bunuh diri', 'passes_accurate': 'umpan akurat',
    'fouls_committed': 'pelanggaran',
}


def kelompok(position):
    return KELOMPOK.get(position or '', 'TENGAH')


def teks_nilai(n):
    """'7,3' — koma, bukan titik. Seluruh angka di app ini bahasa Indonesia."""
    return '–' if n is None else f'{n:.1f}'.replace('.', ',')


def nilai(stat, position):
    """Return dict: nilai, kontribusi, cukup_data, kolom_terisi, bermain.

    `stat` boleh objek model atau dict — apa saja yang punya atribut/kunci
    bernama seperti kolom `PlayerMatchStatistics`.
    """
    ambil_mentah = (
        (lambda k: stat.get(k)) if isinstance(stat, dict) else (lambda k: getattr(stat, k, None))
    )

    def ambil(kolom):
        """Nilai kolom, dengan cadangan buat kolom yang kembar namanya."""
        v = ambil_mentah(kolom)
        if v is None and kolom in PASANGAN_SETARA:
            return ambil_mentah(PASANGAN_SETARA[kolom])
        return v

    kosong = {
        'nilai': None, 'mentah': None, 'dibatasi': False,
        'kontribusi': [], 'teks': '–', 'kolom_terisi': 0,
    }

    # Pemain yang tidak turun tidak dinilai. Ini bukan detail: cadangan yang
    # tidak dipakai punya baris statistik berisi nol, dan nol yang diperlakukan
    # sebagai data menghasilkan 6,0 — nilai yang persis sama dengan pemain yang
    # bermain 90 menit tanpa menonjol. Sebelas pemain "6,0" di daftar bikin
    # kartunya kelihatan rusak, dan yang lebih buruk, kadang tidak.
    menit = ambil_mentah('minutes_played')
    if not menit:
        return {**kosong, 'cukup_data': False, 'bermain': False}

    terisi = [k for k in KOLOM_BUKTI if ambil_mentah(k) is not None]
    if len(terisi) < MIN_KOLOM_TERISI:
        return {**kosong, 'cukup_data': False, 'bermain': True, 'kolom_terisi': len(terisi)}

    bobot = BOBOT[kelompok(position)]
    skor = DASAR
    sumbangan = []
    for kolom, w in bobot.items():
        v = ambil(kolom)
        if not v:
            continue
        delta = w * v
        skor += delta
        sumbangan.append((abs(delta), kolom, v))

    mentah = skor
    skor = max(MIN_NILAI, min(MAKS_NILAI, skor))
    sumbangan.sort(reverse=True)
    kontribusi = [
        f'{int(v) if float(v).is_integer() else round(v, 2)} {SEBUTAN.get(k, k)}'
        for _, k, v in sumbangan[:3]
    ]
    return {
        'nilai': round(skor, 1),
        # Nilai sebelum dipotong langit-langit. Dipakai buat MENGURUTKAN,
        # bukan buat ditampilkan: dua pemain yang sama-sama menembus 10 bukan
        # berarti tampil sama baiknya, dan mengurutkan pakai angka yang sudah
        # dipotong bikin urutannya ditentukan abjad.
        'mentah': round(mentah, 2),
        'dibatasi': mentah > MAKS_NILAI or mentah < MIN_NILAI,
        'teks': teks_nilai(round(skor, 1)),
        'kontribusi': kontribusi,
        'cukup_data': True,
        'bermain': True,
        'kolom_terisi': len(terisi),
    }


def nilai_skuad(stats):
    """Nilai seluruh pemain satu laga, urut menurun, tertinggi/terendah ditandai.

    `stats` = iterable `PlayerMatchStatistics` (sudah difilter ke satu tim).
    """
    baris = []
    for s in stats:
        hasil = nilai(s, s.player.position)
        menit = s.minutes_played or 0
        baris.append(
            {
                'player': s.player,
                'position': s.player.position or '',
                'menit': menit,
                'starter': s.starter,
                'nilai': hasil['nilai'],
                'mentah': hasil['mentah'],
                'dibatasi': hasil['dibatasi'],
                'teks': hasil['teks'],
                'kontribusi': hasil['kontribusi'],
                'cukup_data': hasil['cukup_data'],
                'bermain': hasil['bermain'],
                'sampel_kecil': menit < MENIT_SAMPEL_KECIL,
                'tertinggi': False,
                'terendah': False,
            }
        )

    # Urut: yang punya nilai dulu (menurun), lalu yang datanya kurang, lalu
    # yang tidak turun sama sekali. Tiga keadaan berbeda, tiga tempat berbeda.
    baris.sort(
        key=lambda r: (
            not r['bermain'],
            r['nilai'] is None,
            -(r['mentah'] or 0),
            r['player'].name,
        )
    )

    # Penanda tertinggi/terendah TIDAK diberikan ke sampel kecil. Pemain yang
    # masuk menit 88 lalu mencetak gol akan selalu menang kalau diikutkan, dan
    # "pemain terbaik" versi itu bikin panelnya tidak berguna.
    layak = [r for r in baris if r['nilai'] is not None and not r['sampel_kecil']]
    if layak:
        layak[0]['tertinggi'] = True
        layak[-1]['terendah'] = True
    return baris
