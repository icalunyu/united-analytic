"""Jejak sumber per angka, plus urutan prioritas antar provider.

Masalah yang diselesaikan: satu baris statistik diisi beberapa provider, dan
sebelum ini yang jalan terakhir menang tanpa jejak. Di produksi ada 5.678
baris yang punya `xg` (Understat) sekaligus `rating` (FotMob) — nilai `xg`
yang tersimpan tergantung urutan cron malam itu, dan nggak ada yang bisa
bilang asalnya dari mana.

Dua hal yang diperbaiki di sini:

1. **Deterministik.** Provider berprioritas lebih rendah nggak menimpa nilai
   yang sudah ditulis provider berprioritas lebih tinggi. Urutan cron nggak
   lagi mengubah isi database.
2. **Bisa dilacak.** Tiap field nyimpen kode sumbernya di `field_sources`,
   jadi UI bisa menampilkan chip `sumber: ...` seperti yang diminta prinsip
   kedua design handoff.

Catatan yang perlu diketahui: xG pemain diambil dari Understat sementara xG
tim dari FotMob, jadi total tim nggak akan persis sama dengan jumlah xG
pemainnya. Itu konsekuensi nyata dari menggabung provider — yang berubah,
sekarang ketidakcocokan itu KELIHATAN lewat field_sources, bukan tersembunyi.
"""

from players.models import DataSource

# Urutan default: makin depan makin diprioritaskan. Dasarnya kelengkapan dan
# kedalaman statistik, bukan preferensi.
DEFAULT_PRIORITY = [
    DataSource.FOTMOB,          # 34 field per pemain, satu-satunya yang punya aksi bertahan
    DataSource.UNDERSTAT,       # spesialis xG
    DataSource.ESPN,            # 13 field per pemain
    DataSource.PREMIER_LEAGUE,
    DataSource.FOOTBALL_DATA,
    DataSource.THESPORTSDB,
    DataSource.HIGHLIGHTLY,
    DataSource.API_FOOTBALL,
    DataSource.ESPN_COMMENTARY,  # hasil parsing teks — paling akhir
]

# Pengecualian per field, buat metrik yang punya spesialisnya sendiri.
FIELD_PRIORITY = {
    # Semua turunan xG diambil dari satu sumber yang sama. Mencampurnya bikin
    # angka nggak konsisten satu sama lain (xG dari model A, xA dari model B).
    'xg': [DataSource.UNDERSTAT, DataSource.FOTMOB],
    'xa': [DataSource.UNDERSTAT, DataSource.FOTMOB],
    'xg_chain': [DataSource.UNDERSTAT],
    'xg_buildup': [DataSource.UNDERSTAT],
    'key_passes': [DataSource.UNDERSTAT],
    'minutes_played': [DataSource.UNDERSTAT, DataSource.FOTMOB],
}


def _rank(field, source):
    """Makin kecil makin diprioritaskan. Sumber di luar daftar dapat nilai
    besar — kalah dari semua yang terdaftar, tapi tetap boleh mengisi field
    yang masih kosong."""
    order = FIELD_PRIORITY.get(field, DEFAULT_PRIORITY)
    try:
        return order.index(source)
    except ValueError:
        return len(order) + 1


def resolve_updates(existing_sources, source, values):
    """Saring `values` jadi cuma yang boleh ditulis oleh `source`.

    Return (updates, sources) — dict field yang lolos, dan peta field->sumber
    yang sudah diperbarui. `existing_sources` itu isi field_sources sekarang.

    Pendeteksian konflik dipisah ke `detect_conflicts` di bawah — fungsi ini
    tetap murni memutuskan apa yang boleh ditulis.
    """
    existing_sources = existing_sources or {}
    updates, sources = {}, dict(existing_sources)

    for field, value in values.items():
        if value is None:
            continue
        current = existing_sources.get(field)
        # Field masih kosong, atau sumber ini lebih diprioritaskan.
        if current is None or _rank(field, source) <= _rank(field, current):
            updates[field] = value
            sources[field] = source

    return updates, sources


def _same(a, b):
    """Bandingin nilai lintas tipe. Provider sering ngirim 70 vs 70.0, dan itu
    bukan konflik. Selisih pecahan kecil di metrik float juga bukan — yang
    dicari beda yang beneran berarti."""
    if a is None or b is None:
        return a is b
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    if fa == fb:
        return True
    scale = max(abs(fa), abs(fb), 1.0)
    return abs(fa - fb) / scale < 0.005


# Field hasil MODEL, bukan fakta yang terhitung. Provider beda pakai model
# beda, jadi angkanya memang selalu selisih — xG Dorgu 0.80 menurut Understat
# dan 0.35 menurut FotMob itu bukan data rusak, itu dua model.
#
# Field begini SENGAJA nggak dicatat sebagai konflik. Kalau ikut dicatat, satu
# laga menghasilkan puluhan baris yang nggak bisa ditindaklanjuti siapa pun,
# dan konflik yang beneran penting (menit main beda 3) tenggelam di antaranya.
MODELLED_FIELDS = {
    'xg', 'xa', 'xg_chain', 'xg_buildup', 'xgot', 'xgot_faced',
    'xg_open_play', 'xg_set_play', 'xg_non_penalty', 'goals_prevented',
    'rating',
}


# Toleransi selisih yang sudah diketahui SISTEMATIS, per field.
#
# minutes_played: Understat dan FotMob pakai jam pertandingan berbeda saat
# menghitung waktu tambahan. Diukur di satu laga penuh: 13 pemain yang main 90
# menit sepakat persis, sementara semua yang terlibat pergantian selisih 3-4
# menit. Itu properti kedua provider, bukan kesalahan data, dan nggak butuh
# keputusan analis.
#
# Toleransi, bukan pengecualian total: selisih 40 menit tetap ditandai, karena
# itu memang salah.
FIELD_TOLERANCE = {
    'minutes_played': 5,
}


def detect_conflicts(existing_values, existing_sources, source, values):
    """Cari field di mana `source` nggak sepakat sama nilai yang sudah ada.

    Return list dict {field, kept_source, kept_value, other_source,
    other_value} — sudah diurutkan siapa yang menang menurut prioritas, jadi
    pemanggil tinggal simpan.

    Konflik dicatat TERLEPAS dari siapa yang menang. Yang penting bukan nilai
    mana yang dipakai, tapi bahwa dua sumber melihat hal berbeda — itu sinyal
    buat analis, bukan buat sistem.
    """
    existing_values = existing_values or {}
    existing_sources = existing_sources or {}
    conflicts = []

    for field, value in values.items():
        if value is None:
            continue
        if field in MODELLED_FIELDS:
            continue
        current_source = existing_sources.get(field)
        if current_source is None or current_source == source:
            continue
        current_value = existing_values.get(field)
        if current_value is None or _same(current_value, value):
            continue

        tolerance = FIELD_TOLERANCE.get(field)
        if tolerance is not None:
            try:
                if abs(float(current_value) - float(value)) <= tolerance:
                    continue
            except (TypeError, ValueError):
                pass

        if _rank(field, source) <= _rank(field, current_source):
            kept_source, kept_value = source, value
            other_source, other_value = current_source, current_value
        else:
            kept_source, kept_value = current_source, current_value
            other_source, other_value = source, value

        conflicts.append({
            'field': field,
            'kept_source': kept_source,
            'kept_value': str(kept_value)[:60],
            'other_source': other_source,
            'other_value': str(other_value)[:60],
        })

    return conflicts


def describe_sources(field_sources, fields):
    """Ringkas sumber beberapa field jadi satu label buat UI.

    Contoh: ['fotmob', 'understat'] -> 'FotMob + Understat'. Urutannya ngikut
    prioritas biar labelnya stabil, bukan ngikut urutan field diminta.
    """
    field_sources = field_sources or {}
    found = {field_sources[f] for f in fields if field_sources.get(f)}
    if not found:
        return ''
    ordered = [s for s in DEFAULT_PRIORITY if s in found]
    ordered += sorted(found - set(ordered))
    return ' + '.join(DataSource(s).label.split(' (')[0] for s in ordered)
