"""Model momentum serangan — dihitung sendiri dari play-by-play ESPN.

Ini bukan tiruan angka Sofascore (model mereka tertutup), tapi pendekatan
yang bisa dijelasin ke tim analis: tiap kejadian dikasih bobot bahaya, dikali
faktor kedekatan ke gawang, lalu disebar ke beberapa menit sekitarnya biar
kurvanya nggak patah-patah.

Nilai akhirnya bertanda: positif = tekanan tim tuan rumah, negatif = tim tamu.
"""

# Bobot dasar per jenis play. Angkanya relatif — yang penting urutannya masuk
# akal (gol > tembakan tepat sasaran > tembakan diblok > sepak pojok).
PLAY_WEIGHTS = {
    'goal': 100,
    'goal---header': 100,
    'goal---volley': 100,
    'goal---free-kick': 100,
    'own-goal': 100,
    'penalty---scored': 100,
    'penalty---missed': 75,
    'penalty---saved': 75,
    'shot-on-target': 65,
    'shot-hit-woodwork': 65,
    'shot-blocked': 40,
    'shot-off-target': 35,
    'corner-awarded': 22,
    'free-kick': 12,
    'offside': 10,
    'handball': 8,
    'foul': 10,
}

# Play yang justru nunjukin tekanan LAWAN dari tim yang tercatat. `foul`
# dicatat atas nama tim pelanggar, jadi yang lagi menekan itu lawannya.
# Sama juga buat gol bunuh diri dan handball.
CREDIT_OPPONENT = {'foul', 'own-goal', 'handball'}

# Seberapa jauh 1 kejadian ngaruh ke menit-menit sekitarnya. Index = selisih
# menit dari kejadian; kejadian ngaruh lebih kuat ke depan daripada ke
# belakang, karena tekanan itu menumpuk lalu mereda.
DECAY_FORWARD = (1.0, 0.65, 0.35, 0.15)
DECAY_BACKWARD = (1.0, 0.3)

# Skala akhir kurva (dipakai buat sumbu Y grafik).
MAX_SCALE = 100


def _danger(play):
    """Faktor kedekatan ke gawang, 0.4..1.0.

    `field_x` dari ESPN itu jarak ke gawang yang diserang (0 = di garis
    gawang), jadi makin kecil makin berbahaya. Buat play yang tekanannya
    dikreditkan ke lawan (mis. pelanggaran), logikanya kebalik: pelanggaran
    jauh dari gawang yang diserang si pelanggar berarti dia lagi ketekan
    dalam di daerahnya sendiri.
    """
    if play.field_x is None:
        return 0.7

    closeness = 1.0 - play.field_x if play.play_type not in CREDIT_OPPONENT else play.field_x
    return 0.4 + 0.6 * max(0.0, min(1.0, closeness))


def build_momentum(match, plays=None):
    """Hitung kurva momentum per menit buat 1 match.

    Return list of dict: `{'minute': int, 'value': float}`, value -100..100
    (positif = tuan rumah menekan). List kosong kalau match belum punya play.
    """
    plays = list(plays if plays is not None else match.plays.all())
    if not plays:
        return []

    buckets = {}
    for play in plays:
        weight = PLAY_WEIGHTS.get(play.play_type)
        if not weight or play.team_id is None:
            continue

        team_id = play.team_id
        if play.play_type in CREDIT_OPPONENT:
            team_id = (
                match.away_team_id if team_id == match.home_team_id else match.home_team_id
            )

        # Tuan rumah dorong kurva ke atas, tamu ke bawah.
        sign = 1 if team_id == match.home_team_id else -1
        contribution = sign * weight * _danger(play)

        for offset, factor in enumerate(DECAY_FORWARD):
            minute = play.minute + offset
            buckets[minute] = buckets.get(minute, 0.0) + contribution * factor
        for offset, factor in enumerate(DECAY_BACKWARD):
            if offset == 0:
                continue
            minute = play.minute - offset
            if minute < 0:
                continue
            buckets[minute] = buckets.get(minute, 0.0) + contribution * factor

    if not buckets:
        return []

    last_minute = max(max(buckets), max(p.minute for p in plays))
    peak = max(abs(v) for v in buckets.values()) or 1.0

    return [
        {'minute': minute, 'value': round(buckets.get(minute, 0.0) / peak * MAX_SCALE, 1)}
        for minute in range(1, last_minute + 1)
    ]
