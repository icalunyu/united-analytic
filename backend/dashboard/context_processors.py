"""Context yang muncul di SEMUA halaman.

Kesehatan Sumber itu prinsip desain nomor 2, bukan hiasan: *"Setiap angka
membawa sumbernya... panel Kesehatan Sumber menampilkan status tiap feed.
Kalau tidak jelas asal datanya, jangan ditampilkan."*

`matches/source_health.py` sudah lengkap sejak lama tapi **nggak pernah
dipanggil dari mana pun** — jadi satu-satunya alarm kesegaran feed yang kita
punya nggak pernah kelihatan siapa pun. Ini yang menyambungkannya.
"""

from matches.source_health import source_health


def kesehatan_sumber(request):
    # Empat query ringan (satu per sumber, ambil MatchIngest terbaru). Kalau
    # nanti terasa, cache-nya di sini — bukan dengan menghapus panelnya.
    rows = source_health()
    return {
        'kesehatan_sumber': rows,
        'ada_sumber_bermasalah': any(r['status'] != 'normal' for r in rows),
    }
