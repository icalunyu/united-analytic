from django.db import migrations


def bersihkan(apps, schema_editor):
    """Ubah `shots_faced = 0` yang mustahil jadi NULL.

    ESPN berhenti ngirim angka ini mulai musim 2025 — kuncinya masih ada tapi
    isinya '0' buat semua baris kiper. Yang dibuang cuma baris yang jelas
    kontradiktif: menghadapi nol tembakan TAPI kebobolan atau bikin
    penyelamatan. Baris pemain lapangan yang memang nol dibiarkan.
    """
    P = apps.get_model('matches', 'PlayerMatchStatistics')
    from django.db.models import Q

    P.objects.filter(shots_faced=0).filter(
        Q(goals_conceded__gt=0) | Q(saves__gt=0)
    ).update(shots_faced=None)


def mundur(apps, schema_editor):
    """Sengaja noop — nilai aslinya nol yang nggak berarti apa-apa, jadi
    nggak ada yang perlu dikembalikan."""


class Migration(migrations.Migration):
    dependencies = [('matches', '0019_playermatchstatistics_passes_total')]
    operations = [migrations.RunPython(bersihkan, mundur)]
