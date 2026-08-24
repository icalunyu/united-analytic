"""Tarik umpan berita Manchester United dari beberapa penerbit.

Yang disimpan cuma judul, tautan, waktu terbit, penulis, dan penerbit. Isi
artikel nggak pernah disimpan — lihat docstring `news/models.py`.
"""

import time

import requests
from django.core.management.base import BaseCommand

from matches.models import SourceHeartbeat
from news.feeds import FEEDS, dikutip_siapa, parse, tentang_mu
from news.models import NewsItem
from players.models import DataSource

# Identitas jujur yang bisa dihubungi, bukan penyamaran browser. Kalau penerbit
# mau memblokir kita, mereka harus bisa melakukannya dengan sengaja.
USER_AGENT = (
    'MU-Analytics/1.0 (+https://mu-analytics.musafar.web.id; '
    'analisis internal komunitas suporter)'
)
TIMEOUT = 25

# Manchester Evening News mencantumkan `Crawl-delay: 10` di robots.txt.
# Jeda default lebih longgar dari itu buat semua domain — kita cuma narik
# beberapa feed sekali per 20 menit, nggak ada alasan buru-buru.
JEDA_DETIK = 3
JEDA_REACH = 10


class Command(BaseCommand):
    help = 'Narik berita MU dari daftar feed di news/feeds.py.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--semua', action='store_true',
            help='Simpan semua item, jangan disaring "tentang MU". Buat feed umum.',
        )
        parser.add_argument('--feed', default=None, help='Cuma satu penerbit (cocok sebagian)')

    def handle(self, *args, **options):
        sesi = requests.Session()
        sesi.headers['User-Agent'] = USER_AGENT

        feeds = FEEDS
        if options['feed']:
            feeds = [f for f in FEEDS if options['feed'].lower() in f[0].lower()]
            if not feeds:
                self.stdout.write(self.style.ERROR('Feed nggak ketemu.'))
                return

        baru_total = 0
        gagal = []

        for i, (penerbit, grup, tier, url) in enumerate(feeds):
            if i:
                time.sleep(JEDA_REACH if grup == 'Reach plc' else JEDA_DETIK)

            try:
                r = sesi.get(url, timeout=TIMEOUT)
                r.raise_for_status()
            except requests.RequestException as exc:
                gagal.append(f'{penerbit}: {exc}')
                self.stdout.write(self.style.WARNING(f'  gagal {penerbit}: {exc}'))
                continue

            # Jebakan MEN: URL yang salah tetap balas HTTP 200 tapi isinya
            # {"status":"failure"}. Cek status code doang nggak cukup.
            if not r.content.lstrip()[:1] == b'<':
                gagal.append(f'{penerbit}: balasan bukan XML')
                self.stdout.write(
                    self.style.WARNING(
                        f'  {penerbit}: HTTP 200 tapi isinya bukan XML — '
                        f'kemungkinan URL feed salah'
                    )
                )
                continue

            item = parse(r.content)
            baru = 0
            for it in item:
                if not options['semua'] and not tentang_mu(it['title']):
                    continue
                _, dibuat = NewsItem.objects.update_or_create(
                    url=it['url'][:600],
                    defaults={
                        'publisher': penerbit,
                        'publisher_group': grup,
                        'tier': tier,
                        'title': it['title'][:400],
                        'published_at': it['published_at'],
                        'author': (it['author'] or '')[:160],
                        'quoted_source': dikutip_siapa(it['title']),
                    },
                )
                baru += 1 if dibuat else 0
            baru_total += baru
            self.stdout.write(f'  {penerbit:<26}{len(item):>3} item · {baru} baru')

        SourceHeartbeat.objects.update_or_create(
            source=DataSource.NEWS,
            defaults={'note': f'{len(feeds) - len(gagal)}/{len(feeds)} feed, {baru_total} baru'},
        )

        if gagal:
            self.stdout.write(self.style.WARNING(f'{len(gagal)} feed gagal.'))
        self.stdout.write(
            self.style.SUCCESS(
                f'Selesai. {baru_total} berita baru, total {NewsItem.objects.count()} tersimpan.'
            )
        )
