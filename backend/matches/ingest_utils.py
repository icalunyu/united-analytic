"""Helper penarikan yang dipakai bareng beberapa command."""

import json

from matches.models import FieldConflict, RawPayload
from players.provenance import detect_conflicts


def store_raw(source, kind, key, payload):
    """Simpen respons mentah provider supaya laga bisa diproses ulang tanpa
    narik lagi. Cuma versi terakhir per (sumber, jenis, kunci)."""
    if not payload:
        return
    RawPayload.objects.update_or_create(
        source=source,
        kind=kind,
        key=str(key),
        defaults={
            'payload': payload,
            'size_bytes': len(json.dumps(payload, separators=(',', ':'))),
        },
    )


def record_conflicts(row, match, source, values, player=None, team=None):
    """Catat field yang nilainya diperselisihkan dua sumber.

    Dipanggil SEBELUM row ditimpa, karena yang dibandingkan adalah nilai lama
    versus nilai yang masuk.
    """
    current = {f: getattr(row, f, None) for f in values}
    found = detect_conflicts(current, row.field_sources, source, values)
    for c in found:
        FieldConflict.objects.update_or_create(
            match=match,
            player=player,
            team=team,
            field=c['field'],
            other_source=c['other_source'],
            defaults={
                'kept_source': c['kept_source'],
                'kept_value': c['kept_value'],
                'other_value': c['other_value'],
            },
        )
    return len(found)
