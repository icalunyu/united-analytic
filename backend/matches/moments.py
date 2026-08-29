"""Detektor momen dari data akhir laga — bagian "asal sistem" dari PS-04.

Handoff: *"jalankan detektor sekali lagi pada data lengkap, temuan baru
ditandai asal sistem"*. Jadi ini pelengkap momen yang ditandai analis waktu
nonton, bukan penggantinya. Yang ditangkap di sini justru yang biasanya
terlewat waktu menonton: selisih gol dengan xG, angka yang menyimpang jauh
dari kebiasaan, penyelamatan yang menyelamatkan clean sheet.

Tiap detektor punya ambang yang ditulis eksplisit di konstanta, bukan
disembunyikan di dalam `if`. Ambang yang bisa dibaca itu ambang yang bisa
diperdebatkan — dan momen yang salah di sini berakhir jadi konten publik.
"""

from matches.models import SavedMoment

# Ambang tiap detektor.
MIN_GOL_GANDA = 2
MIN_SELISIH_XG = 1.0        # |gol − xG| satu tim
MIN_Z_ANGKA = 2.0           # simpangan baku di key_numbers
MIN_SAVES_CLEAN_SHEET = 4
MIN_NILAI_MENONJOL = 8.0
MIN_PELUANG_TERBUANG = 3


def _fmt(v, desimal=2):
    if v is None:
        return '–'
    if float(v).is_integer():
        return str(int(v))
    return f'{v:.{desimal}f}'.rstrip('0').rstrip('.').replace('.', ',')


def deteksi(match, baris_mu, baris_lawan, angka, nilai_pemain, stats_mu):
    """[(menit, teks, angka_teks, kartu_asal)] — fungsi murni.

    Menit boleh None: sebagian temuan (mis. selisih xG) berlaku untuk seluruh
    laga, bukan untuk satu menit tertentu. Memaksakan menit palsu ke temuan
    seperti itu bikin baris di UI kelihatan seperti kejadian yang bisa
    diputar ulang, padahal bukan.
    """
    from matches import scoreline

    hasil = []
    mu_gol, lawan_gol = scoreline.skor(match)

    # 1. Pencetak gol lebih dari satu.
    for s in stats_mu:
        if (s.goals or 0) >= MIN_GOL_GANDA:
            hasil.append(
                (None, f'{s.player.name} mencetak {s.goals} gol dalam satu laga.',
                 f'{s.goals} gol', 'PS-03')
            )

    # 2. Selisih gol dengan xG — panen berlebih atau pemborosan.
    if baris_mu is not None and baris_mu.xg is not None and mu_gol is not None:
        selisih = mu_gol - baris_mu.xg
        if abs(selisih) >= MIN_SELISIH_XG:
            arah = 'lebih banyak' if selisih > 0 else 'lebih sedikit'
            hasil.append(
                (None,
                 f'United mencetak {arah} dari yang diharapkan peluangnya: '
                 f'{mu_gol} gol dari {_fmt(baris_mu.xg)} xG.',
                 f'{_fmt(abs(selisih))} xG', 'PS-02')
            )

    # 3. Angka yang paling menyimpang dari kebiasaan musim.
    for a in angka:
        if abs(a['z']) >= MIN_Z_ANGKA:
            hasil.append(
                (None,
                 f'{a["label"]} {a["nilai_teks"]} — {a["simpangan_teks"]}, '
                 f'{a["pembanding"]}.',
                 a['nilai_teks'], 'PS-02')
            )

    # 4. Clean sheet yang benar-benar dikerjakan kiper.
    if lawan_gol == 0 and baris_mu is not None:
        saves = baris_mu.saves or 0
        if saves >= MIN_SAVES_CLEAN_SHEET:
            hasil.append(
                (None,
                 f'Gawang United tidak kebobolan dengan {saves} penyelamatan.',
                 f'{saves} penyelamatan', 'PS-02')
            )

    # 5. Nilai pemain yang menonjol.
    for r in nilai_pemain:
        if r['nilai'] is not None and r['nilai'] >= MIN_NILAI_MENONJOL and not r['sampel_kecil']:
            ekor = f' — {", ".join(r["kontribusi"])}' if r['kontribusi'] else ''
            # Pakai `teks`, bukan `nilai`: angka yang masuk momen ujungnya
            # masuk prompt konten, dan di situ formatnya tidak boleh berbeda
            # dari yang tampil di kartu.
            hasil.append(
                (None, f'{r["player"].name} dinilai {r["teks"]}{ekor}.',
                 r['teks'], 'PS-03')
            )

    # 6. Peluang emas yang terbuang.
    if baris_mu is not None and (baris_mu.big_chances_missed or 0) >= MIN_PELUANG_TERBUANG:
        hasil.append(
            (None,
             f'United membuang {baris_mu.big_chances_missed} peluang emas.',
             f'{baris_mu.big_chances_missed} peluang', 'PS-02')
        )

    return hasil


def segarkan(match, temuan):
    """Simpan temuan sistem, tanpa menggandakan yang sudah ada.

    Momen asal analis tidak pernah disentuh fungsi ini — itu tulisan manusia,
    dan detektor tidak berhak menimpanya. Temuan sistem yang tidak lagi
    muncul juga tidak dihapus: kalau analis sudah mencentangnya untuk prompt,
    menghapusnya diam-diam bikin isi prompt berubah tanpa ada yang menyentuh.
    """
    ada = set(
        SavedMoment.objects.filter(
            match=match, origin=SavedMoment.Asal.SISTEM
        ).values_list('origin_card', 'text')
    )
    baru = []
    for menit, teks, angka_teks, kartu in temuan:
        if (kartu, teks) in ada:
            continue
        baru.append(
            SavedMoment(
                match=match,
                minute=menit,
                text=teks[:300],
                figure=angka_teks[:60],
                origin_card=kartu,
                origin=SavedMoment.Asal.SISTEM,
                # Temuan sistem masuk TIDAK tercentang. Analis yang memutuskan
                # apa yang layak jadi konten; kalau default-nya tercentang,
                # prompt terisi sendiri oleh hal-hal yang belum dibaca siapa pun.
                selected=False,
            )
        )
    if baru:
        SavedMoment.objects.bulk_create(baru, ignore_conflicts=True)
    return len(baru)
