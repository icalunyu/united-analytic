"""Mendeteksi laga yang sedang berjalan, buat penarikan mode live.

Fungsi murni, sesuai pola `workload.py` dan `ratings.py` — satu-satunya yang
menyentuh DB dipisah di bawah.

**Kenapa jendela jam, bukan `status`.** Godaan pertamanya jelas: cari laga
yang `status`-nya LIVE. Itu tidak bisa jalan, dan alasannya melingkar —
`status` di DB kita cuma berubah kalau kita menarik data, dan yang menentukan
kapan kita menarik justru `status` itu. Pada menit kick-off statusnya masih
`NS`, jadi mode live tidak akan pernah menyala sama sekali.

Jadi yang dipakai jam dinding: laga yang jadwalnya sedang berlangsung DAN
belum tercatat final. `status` tetap dibaca, tapi cuma sebagai penguat — kalau
provider sudah bilang LIVE, kita percaya tanpa perlu jendela.

Jendelanya sengaja lebar ke belakang: 3 jam menampung babak tambahan, adu
penalti, dan jeda panjang. Menarik beberapa kali lebih banyak sesudah peluit
panjang jauh lebih murah daripada kehilangan gol menit 90+8.
"""

from datetime import timedelta

# Susunan resmi biasanya terbit ~1 jam sebelum kick-off, tapi menarik sejam
# penuh sebelum peluit cuma menghabiskan panggilan. 20 menit cukup buat
# menangkap susunan yang terlambat terbit tanpa membakar kuota.
JENDELA_SEBELUM = timedelta(minutes=20)
JENDELA_SESUDAH = timedelta(hours=3)


def sedang_berjalan(match, sekarang, status_live=(), status_final=()):
    """True kalau laga ini layak ditarik ulang sekarang."""
    if match.status in status_final:
        return False
    if match.status in status_live:
        return True
    if match.kickoff_at is None:
        return False
    return (
        match.kickoff_at - JENDELA_SEBELUM
        <= sekarang
        <= match.kickoff_at + JENDELA_SESUDAH
    )


def slug_yang_perlu(laga, pemetaan):
    """Slug kompetisi yang benar-benar perlu ditembak, plus yang tidak dikenal.

    Return (slugs, tanpa_slug). `tanpa_slug` bukan kegagalan diam-diam — dia
    dilaporkan command supaya kompetisi baru yang belum dipetakan kelihatan,
    bukan hilang begitu saja.
    """
    slugs, tanpa = [], []
    for m in laga:
        s = pemetaan(m.league_name)
        if s is None:
            tanpa.append(m)
        elif s not in slugs:
            slugs.append(s)
    return slugs, tanpa


# ------------------------------------------------------------------ DB


def laga_berjalan(sekarang):
    """Laga MU yang sedang berlangsung. Query murah, tanpa jaringan."""
    from django.db.models import Q

    from matches.models import Match

    final = (Match.Status.FINISHED, Match.Status.EXTRA_TIME, Match.Status.PENALTIES)
    live = (Match.Status.LIVE, Match.Status.HALFTIME)

    kandidat = (
        Match.objects.filter(
            Q(home_team__is_manchester_united=True) | Q(away_team__is_manchester_united=True)
        )
        .exclude(status__in=final)
        .filter(
            kickoff_at__gte=sekarang - JENDELA_SESUDAH,
            kickoff_at__lte=sekarang + JENDELA_SEBELUM,
        )
        .select_related('home_team', 'away_team')
        .order_by('kickoff_at')
    )
    return [
        m for m in kandidat
        if sedang_berjalan(m, sekarang, status_live=live, status_final=final)
    ]
