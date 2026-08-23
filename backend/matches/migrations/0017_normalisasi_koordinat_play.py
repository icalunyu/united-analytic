from django.db import migrations
from django.db.models import Max


def normalkan(apps, schema_editor):
    """Samakan koordinat play lama ke konvensi 0..1 dengan 0 = di gawang lawan.

    ESPN mulai mengirim format berbeda di laga musim 2026: skalanya 0..100 DAN
    arahnya terbalik (100 = di gawang, bukan 0). Waktu migrasi ini ditulis, 303
    play di 6 laga memakai format itu.

    Deteksinya per laga. Nilai tunggal tidak bisa dibedakan — 0.5 sah di kedua
    format — tapi satu laga tidak pernah mencampur keduanya (dicek ke 419 laga
    di produksi: nol yang campur), jadi maksimum per laga sudah cukup.
    """
    MatchPlay = apps.get_model('matches', 'MatchPlay')

    terdampak = (
        MatchPlay.objects.filter(field_x__isnull=False)
        .values('match_id')
        .annotate(mx=Max('field_x'))
        .filter(mx__gt=1)
        .values_list('match_id', flat=True)
    )

    for match_id in list(terdampak):
        for play in MatchPlay.objects.filter(match_id=match_id):
            ubah = []
            if play.field_x is not None and play.field_x > 1:
                play.field_x = 1.0 - (play.field_x / 100.0)
                ubah.append('field_x')
            if play.field_y is not None and play.field_y > 1:
                play.field_y = play.field_y / 100.0
                ubah.append('field_y')
            if ubah:
                play.save(update_fields=ubah)


def mundur(apps, schema_editor):
    """Kembalikan ke format ESPN yang baru.

    Tidak sepenuhnya lossless: laga yang memang sudah 0..1 sejak awal tidak
    bisa dibedakan lagi dari yang sudah dinormalkan, jadi mundur hanya aman
    kalau dijalankan langsung sesudah maju.
    """
    raise migrations.exceptions.IrreversibleError(
        'Normalisasi koordinat tidak bisa dibalik: setelah dinormalkan, laga '
        'format lama dan format baru jadi tidak terbedakan.'
    )


class Migration(migrations.Migration):
    dependencies = [('matches', '0016_predictionsnapshot_lineupslot_hypothesisitem_and_more')]
    operations = [migrations.RunPython(normalkan, mundur)]
