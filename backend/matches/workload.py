"""Beban pemain & kandidat rotasi — rumus LV-08 dari inventaris kartu.

Fungsi murni, sesuai permintaan handoff buat Tahap 3: *"Tulis sebagai fungsi
murni dengan tes, bukan query yang tersebar di UI."*

Rumus aslinya, apa adanya dari `Inventaris Card.dc.html` LV-08:

    beban            = total menit 14 hari dibagi 450 (patokan tiga laga penuh)
    kepadatan jadwal = 1 kalau ada laga dalam 4 hari, 0 kalau tidak
    riwayat          = 1 kalau pernah cedera otot dalam 6 bulan
    skor             = 0,5 x beban + 0,3 x kepadatan + 0,2 x riwayat

Satu rumus ini dirujuk tiga kartu berbeda: kolom "Beban 14 hr" di halaman
Skuad (SQ-02), Kandidat Rotasi (LV-08), dan Duel Kunci (PR-08). Itu alasan dia
ditulis sekali di sini, bukan tiga kali di tiga view.
"""

from datetime import timedelta

# Patokan "tiga laga penuh dalam dua minggu". Angkanya dari handoff, bukan
# karangan sendiri — jangan diubah tanpa mengubah dokumennya juga.
MENIT_PATOKAN = 450
JENDELA_HARI = 14
PADAT_HARI = 4          # laga berikutnya dalam N hari = jadwal padat
RIWAYAT_BULAN = 6

BOBOT_BEBAN = 0.5
BOBOT_KEPADATAN = 0.3
BOBOT_RIWAYAT = 0.2

# Ambang tingkat kemendesakan. Handoff cuma nyebut tiga varian (mendesak /
# perlu diawasi / aman) tanpa angka, jadi ambangnya diturunkan dari rumusnya
# sendiri: pemain yang menit-nya PENUH (450/450 = 1,0) dapat 0,5 dari
# komponen beban saja — itu batas bawah "mendesak" yang masuk akal.
AMBANG_MENDESAK = 0.5
AMBANG_AWASI = 0.3

# Cedera yang dihitung sebagai "cedera otot". Dicocokkan ke teks bebas
# `Injury.reason`, yang di produksi isinya seperti 'Hamstring injury',
# 'Muscle injury', 'Thigh problems', 'Calf injury'.
#
# Sengaja SEMPIT. 'Knock', 'Ill', 'Unknown', dan 'Ankle injury' TIDAK masuk —
# memasukkannya bikin hampir semua pemain punya riwayat, dan komponen yang
# selalu bernilai 1 nggak membedakan apa-apa.
KATA_OTOT = (
    'hamstring', 'muscle', 'thigh', 'calf', 'groin', 'quad', 'adductor',
    'otot', 'paha', 'betis',
)


def cedera_otot(reason):
    """True kalau teks alasan cedera menunjuk ke otot."""
    teks = (reason or '').lower()
    return any(k in teks for k in KATA_OTOT)


def skor_rotasi(menit_14_hari, jadwal_padat, punya_riwayat_otot):
    """Skor LV-08. Makin tinggi makin layak diistirahatkan.

    `menit_14_hari` boleh melebihi 450 (pemain yang main lebih dari tiga laga
    penuh) — komponennya sengaja TIDAK dibatasi di 1,0, karena beban 600 menit
    memang lebih berat daripada 450 dan kartunya ada justru buat menemukan itu.
    """
    beban = (menit_14_hari or 0) / MENIT_PATOKAN
    return round(
        BOBOT_BEBAN * beban
        + BOBOT_KEPADATAN * (1 if jadwal_padat else 0)
        + BOBOT_RIWAYAT * (1 if punya_riwayat_otot else 0),
        3,
    )


def tingkat(skor):
    """'mendesak' | 'awasi' | 'aman'."""
    if skor >= AMBANG_MENDESAK:
        return 'mendesak'
    if skor >= AMBANG_AWASI:
        return 'awasi'
    return 'aman'


def alasan(menit, jadwal_padat, punya_riwayat_otot):
    """Kalimat pendek yang menjelaskan skornya — biar angkanya nggak telanjang."""
    bagian = [f'{menit} menit dalam {JENDELA_HARI} hari']
    if jadwal_padat:
        bagian.append(f'laga lagi dalam {PADAT_HARI} hari')
    if punya_riwayat_otot:
        bagian.append(f'riwayat cedera otot {RIWAYAT_BULAN} bulan terakhir')
    return ' · '.join(bagian)


def beban_skuad(team, sekarang, pemain=None):
    """Hitung beban seluruh skuad. Satu-satunya fungsi di modul ini yang
    menyentuh DB — sisanya murni supaya gampang dites.

    Return list dict urut skor menurun.
    """
    from django.db.models import Q, Sum

    from matches.models import Match, PlayerMatchStatistics
    from players.models import Injury, Player

    pemain = pemain if pemain is not None else Player.objects.filter(
        team=team, is_active=True
    )
    batas = sekarang - timedelta(days=JENDELA_HARI)

    menit = dict(
        PlayerMatchStatistics.objects.filter(
            player__in=pemain,
            match__kickoff_at__gte=batas,
            match__kickoff_at__lte=sekarang,
            minutes_played__isnull=False,
        )
        .values_list('player_id')
        .annotate(total=Sum('minutes_played'))
    )

    # Kepadatan jadwal berlaku untuk SELURUH tim, bukan per pemain — laga
    # berikutnya sama buat semua orang.
    laga_berikut = (
        Match.objects.filter(Q(home_team=team) | Q(away_team=team))
        .filter(kickoff_at__gt=sekarang)
        .order_by('kickoff_at')
        .first()
    )
    jadwal_padat = bool(
        laga_berikut
        and laga_berikut.kickoff_at <= sekarang + timedelta(days=PADAT_HARI)
    )

    sejak = sekarang.date() - timedelta(days=RIWAYAT_BULAN * 30)
    riwayat = {
        i.player_id
        for i in Injury.objects.filter(player__in=pemain, start_date__gte=sejak)
        if cedera_otot(i.reason)
    }

    hasil = []
    for p in pemain:
        m = menit.get(p.pk, 0)
        s = skor_rotasi(m, jadwal_padat, p.pk in riwayat)
        hasil.append({
            'player': p,
            'menit': m,
            'skor': s,
            'tingkat': tingkat(s),
            'jadwal_padat': jadwal_padat,
            'riwayat_otot': p.pk in riwayat,
            'alasan': alasan(m, jadwal_padat, p.pk in riwayat),
        })
    hasil.sort(key=lambda r: -r['skor'])
    return hasil
