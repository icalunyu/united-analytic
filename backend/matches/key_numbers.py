"""Angka Penentu Pertandingan — PS-02.

Handoff, apa adanya:

    hitung sekitar 20 metrik penuh untuk kedua tim
    untuk tiap metrik hitung selisih dari rata-rata musim United dalam satuan
      simpangan baku
    ambil empat dengan nilai mutlak selisih terbesar
    beri arah: angka yang menguntungkan hijau, merugikan merah

Yang bikin kartu ini beda dari "empat angka statistik": angkanya **tidak
tetap**. Yang tampil adalah empat metrik yang paling jauh dari kebiasaan MU
musim itu — jadi laga yang dimenangkan lewat penguasaan bola dan laga yang
dimenangkan lewat serangan balik menampilkan empat angka yang berbeda, dan
itu memang maksudnya.

**Kenapa simpangan baku, dan kapan dia menolak menjawab.** Z-score butuh
sebaran; dari tiga laga, satu laga aneh menggeser rata-ratanya sendiri dan
semua angka jadi kelihatan normal. Di bawah `MIN_SAMPEL` laga, modul ini
mengembalikan daftar kosong dan halaman bilang datanya belum cukup — bukan
menampilkan empat angka yang perhitungannya tidak bisa dipertanggungjawabkan.
"""

import statistics

# Di bawah ini, simpangan baku belum berarti apa-apa.
MIN_SAMPEL = 6

# Metrik yang dibandingkan. `arah` = +1 kalau makin besar makin bagus buat MU,
# −1 kalau makin besar makin buruk. `lawan` = diambil dari baris tim LAWAN,
# bukan baris MU (mis. tembakan yang kita hadapi).
METRIK = [
    ('possession_pct', 'Penguasaan bola', '%', +1, False),
    ('shots_total', 'Tembakan', '', +1, False),
    ('shots_on_target', 'Tembakan tepat sasaran', '', +1, False),
    ('big_chances', 'Peluang emas', '', +1, False),
    ('big_chances_missed', 'Peluang emas terbuang', '', -1, False),
    ('xg', 'xG', '', +1, False),
    ('xgot', 'xGOT', '', +1, False),
    ('xg_open_play', 'xG permainan terbuka', '', +1, False),
    ('corners', 'Sepak pojok', '', +1, False),
    ('touches_opp_box', 'Sentuhan di kotak lawan', '', +1, False),
    ('passes_accurate', 'Umpan akurat', '', +1, False),
    ('passes_opposition_half', 'Umpan di daerah lawan', '', +1, False),
    ('crosses_accurate', 'Umpan silang akurat', '', +1, False),
    ('long_balls_accurate', 'Umpan panjang akurat', '', +1, False),
    ('dribbles_succeeded', 'Dribel sukses', '', +1, False),
    ('duels_won', 'Duel dimenangkan', '', +1, False),
    ('tackles_won', 'Tekel sukses', '', +1, False),
    ('interceptions', 'Intersep', '', +1, False),
    ('clearances_effective', 'Sapuan efektif', '', -1, False),
    ('fouls', 'Pelanggaran', '', -1, False),
    ('offsides', 'Offside', '', -1, False),
    # Sisi lawan — ini yang bikin "kenapa kalah" bisa terjawab, bukan cuma
    # "apa yang kita lakukan".
    ('shots_total', 'Tembakan yang dihadapi', '', -1, True),
    ('shots_on_target', 'Tembakan tepat yang dihadapi', '', -1, True),
    ('xg', 'xG yang dihadapi', '', -1, True),
    ('big_chances', 'Peluang emas lawan', '', -1, True),
    ('touches_opp_box', 'Sentuhan lawan di kotak kita', '', -1, True),
]


def _angka(v):
    return None if v is None else float(v)


def kunci(nama, lawan):
    return f'{"lawan:" if lawan else ""}{nama}'


def z(nilai, contoh):
    """Selisih dari rata-rata dalam satuan simpangan baku, atau None."""
    contoh = [c for c in contoh if c is not None]
    if len(contoh) < MIN_SAMPEL:
        return None, None, None
    rata = statistics.fmean(contoh)
    sb = statistics.pstdev(contoh)
    if sb == 0:
        return None, rata, sb
    return (nilai - rata) / sb, rata, sb


def format_angka(v, satuan):
    if v is None:
        return '–'
    if float(v).is_integer():
        teks = str(int(v))
    else:
        teks = f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
    return f'{teks}{satuan}'


def hitung(baris_mu, baris_lawan, riwayat_mu, riwayat_lawan, jumlah=4):
    """Empat angka penentu.

    `baris_mu` / `baris_lawan` = `MatchTeamStatistics` laga ini.
    `riwayat_mu` / `riwayat_lawan` = daftar baris musim yang sama, TIDAK
    termasuk laga ini — memasukkan laganya sendiri ke pembanding menarik
    rata-rata ke arah nilai yang sedang diuji dan mengecilkan simpangannya.

    Fungsi murni: tidak ada query di sini.
    """
    if baris_mu is None:
        return []

    hasil = []
    for nama, label, satuan, arah, dari_lawan in METRIK:
        sumber = baris_lawan if dari_lawan else baris_mu
        if sumber is None:
            continue
        nilai = _angka(getattr(sumber, nama, None))
        if nilai is None:
            continue

        riwayat = riwayat_lawan if dari_lawan else riwayat_mu
        contoh = [_angka(getattr(r, nama, None)) for r in riwayat]
        skor, rata, _ = z(nilai, contoh)
        if skor is None:
            continue

        condong = skor * arah  # positif = menguntungkan MU
        hasil.append(
            {
                'kunci': kunci(nama, dari_lawan),
                'label': label,
                'nilai': nilai,
                'nilai_teks': format_angka(nilai, satuan),
                'rata': rata,
                'rata_teks': format_angka(round(rata, 2), satuan),
                'z': round(skor, 2),
                'condong': round(condong, 2),
                'arah': 'untung' if condong > 0.5 else ('rugi' if condong < -0.5 else 'netral'),
                'pembanding': (
                    f'rata-rata musim {format_angka(round(rata, 2), satuan)}'
                ),
                # Koma, bukan titik — kalimat ini masuk laporan dan prompt
                # berbahasa Indonesia, dan satu angka bertitik di tengah
                # angka-angka berkoma langsung kelihatan seperti salah salin.
                'simpangan_teks': (
                    f'{abs(skor):.1f}'.replace('.', ',') + '× simpangan baku '
                    f'{"di atas" if skor > 0 else "di bawah"} kebiasaan'
                ),
            }
        )

    hasil.sort(key=lambda h: -abs(h['z']))
    return hasil[:jumlah]


# ------------------------------------------------------------------ DB


def untuk_laga(match, jumlah=4):
    """Angka penentu satu laga. Satu-satunya fungsi yang menyentuh DB."""
    from matches.models import Match, MatchTeamStatistics

    mu_home = match.home_team.is_manchester_united
    mu = match.home_team if mu_home else match.away_team
    lawan = match.away_team if mu_home else match.home_team

    baris = {b.team_id: b for b in MatchTeamStatistics.objects.filter(match=match)}
    baris_mu, baris_lawan = baris.get(mu.pk), baris.get(lawan.pk)

    final = [Match.Status.FINISHED, Match.Status.EXTRA_TIME, Match.Status.PENALTIES]
    riwayat_mu = list(
        MatchTeamStatistics.objects.filter(
            team=mu, match__season=match.season, match__status__in=final
        ).exclude(match=match)
    )
    # Pembanding untuk metrik sisi lawan tetap "kebiasaan MU", bukan kebiasaan
    # lawan — pertanyaannya "apakah laga ini tidak biasa BUAT KITA", dan lawan
    # berganti tiap pekan sehingga sebarannya tidak pernah terbentuk.
    id_laga_mu = {r.match_id for r in riwayat_mu} | {match.pk}
    riwayat_lawan = list(
        MatchTeamStatistics.objects.filter(match_id__in=id_laga_mu)
        .exclude(team=mu)
        .exclude(match=match)
    )
    return hitung(baris_mu, baris_lawan, riwayat_mu, riwayat_lawan, jumlah=jumlah)
