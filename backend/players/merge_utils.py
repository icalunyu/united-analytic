"""Pemindahan referensi antar row — dipakai bareng sama command yang
ngerapiin data (merge_duplicates & clean_commentary_players)."""

from django.db import IntegrityError, transaction


def absorb(loser, canonical, on_conflict_delete=True):
    """Pindahin semua yang nunjuk ke `loser` supaya nunjuk ke `canonical`,
    lalu hapus `loser`.

    Referensi FK di-enumerate dinamis dari _meta, bukan di-hardcode: mayoritas
    FK ke Team/Player itu CASCADE, jadi satu referensi kelewat berarti row
    lain (Match, MatchEvent, ...) ikut kehapus diam-diam pas `loser` dibuang.

    Return dict {label_model: jumlah_baris_dipindah} buat pelaporan.
    """
    model = type(loser)
    moved = {}

    with transaction.atomic():
        for rel in model._meta.related_objects:
            field_name = rel.field.name
            label = f'{rel.related_model._meta.label}.{field_name}'

            for row in rel.related_model.objects.filter(**{field_name: loser}):
                setattr(row, field_name, canonical)
                try:
                    # Savepoint per baris: bentrok unique constraint itu hal
                    # yang diharapkan (mis. `loser` dan `canonical` sama-sama
                    # punya PlayerMatchStatistics buat match yang sama), bukan
                    # error fatal.
                    with transaction.atomic():
                        row.save(update_fields=[rel.field.attname])
                    moved[label] = moved.get(label, 0) + 1
                except IntegrityError:
                    if on_conflict_delete:
                        row.delete()
                    else:
                        raise

        loser.delete()

    return moved
