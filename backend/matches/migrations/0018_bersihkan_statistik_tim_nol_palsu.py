from django.db import migrations

# Field yang diisi ESPN. field_sources, match, team, updated_at sengaja tidak
# ikut — provenance-nya tetap berguna sebagai catatan bahwa laga ini pernah
# ditarik, cuma isinya memang tidak ada.
FIELD_ESPN = [
    'possession_pct', 'shots_total', 'shots_on_target', 'corners', 'fouls',
    'offsides', 'yellow_cards', 'red_cards', 'passes_total', 'passes_accurate',
    'saves', 'shots_blocked', 'crosses_total', 'crosses_accurate',
    'long_balls_total', 'long_balls_accurate', 'tackles_total', 'tackles_won',
    'interceptions', 'clearances_total', 'clearances_effective',
    'penalty_goals', 'penalty_shots',
]


def kosongkan(apps, schema_editor):
    """Ubah nol-palsu ESPN jadi NULL supaya tidak ikut rata-rata.

    ESPN mengirim blok statistik lengkap berisi '0' untuk laga yang datanya
    tidak dia punya. Karena non-null, angka itu lolos semua penyaring: rata-rata
    penguasaan bola MU musim 2022 terbaca 49,4% padahal 56,4%.

    Deteksinya penguasaan bola DAN total umpan sama-sama nol — tim yang bermain
    bisa saja nol tembakan, tapi tidak mungkin nol penguasaan sekaligus nol
    umpan. Baris yang masih menyimpan nilai bukan-nol di field lain (mis. dari
    FotMob) sengaja dilewati; itu bukan nol-palsu, cuma sebagian kolom kosong.
    """
    MatchTeamStatistics = apps.get_model('matches', 'MatchTeamStatistics')

    kandidat = MatchTeamStatistics.objects.filter(possession_pct=0, passes_total=0)
    for row in kandidat:
        punya_isi_lain = any(
            getattr(row, f) not in (None, 0)
            for f in FIELD_ESPN
            if f not in ('possession_pct', 'passes_total')
        )
        if punya_isi_lain:
            continue
        for f in FIELD_ESPN:
            setattr(row, f, None)
        row.save(update_fields=FIELD_ESPN)


class Migration(migrations.Migration):
    dependencies = [('matches', '0017_normalisasi_koordinat_play')]
    operations = [migrations.RunPython(kosongkan, migrations.RunPython.noop)]
