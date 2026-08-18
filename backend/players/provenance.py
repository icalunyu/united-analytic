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
