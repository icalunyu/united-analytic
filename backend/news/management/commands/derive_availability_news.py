"""Turunkan status ketersediaan dari judul berita yang sudah tersimpan.

Tidak menyentuh jaringan sama sekali — dia membaca `NewsItem` yang sudah
ditarik `pull_news`. Jadi aman dijalankan sesering apa pun, dan kalau hasilnya
mencurigakan bisa diulang tanpa membebani penerbit mana pun.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from news import availability
from news.models import NewsItem
from players.models import Player, Team


class Command(BaseCommand):
    help = (
        'Baca judul berita 10 hari terakhir, tandai pemain MU yang disebut '
        'absen/diragukan/skorsing, simpan sebagai PlayerAvailability sumber '
        'NEWS. Hasilnya jadi pembanding buat FPL di panel Konflik Sumber.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Tampilkan temuan tanpa menulis apa pun ke DB.',
        )

    def handle(self, *args, **options):
        sekarang = timezone.now()
        mu = Team.objects.filter(is_manchester_united=True).first()
        if mu is None:
            self.stderr.write('Nggak ada Team bertanda is_manchester_united.')
            return

        pemain = list(Player.objects.filter(team=mu, is_active=True))
        berita = list(
            NewsItem.objects.filter(
                published_at__gte=sekarang - availability.UMUR_MAKS
            ).order_by('published_at')
        )
        self.stdout.write(f'{len(berita)} berita dalam jendela, {len(pemain)} pemain aktif')

        hasil = availability.temuan(berita, pemain, sekarang)
        for player, status, item in hasil:
            self.stdout.write(f'  [{status}] {player.name} ← {item.publisher}: {item.title[:70]}')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(f'Dry run — {len(hasil)} temuan, nggak ditulis.'))
            return

        ditulis = availability.simpan(hasil, sekarang)
        dihapus = availability.bersihkan(sekarang, {p.pk for p, _, _ in hasil})
        self.stdout.write(
            self.style.SUCCESS(f'{ditulis} status ditulis, {dihapus} turunan lama dihapus.')
        )
