"""Umpan berita Manchester United.

**Apa yang disimpan, dan apa yang TIDAK.** Cuma judul, tautan, waktu terbit,
nama penulis, dan nama penerbit. Isi artikel **tidak pernah** disimpan — itu
karya berhak cipta milik penerbitnya, dan app ini cuma perlu tahu "siapa
memberitakan apa, kapan", bukan isinya.

Parser sengaja pakai `xml.etree` stdlib dan cuma membaca empat elemen yang
dibutuhkan. Feed WordPress (Metro, talkSPORT, blog suporter) mengirim
`<content:encoded>` berisi ARTIKEL UTUH; kalau dipakai pustaka yang menyerap
seluruh entri lalu disimpan apa adanya, kita menyalin artikel tanpa sadar.
Dengan hanya membaca elemen yang disebut eksplisit, jebakan itu nggak pernah
punya kesempatan.
"""

from django.db import models


class NewsSourceTier(models.TextChoices):
    """Tingkat reliabilitas sumber, sesuai aturan redaksi di handoff:
    A boleh langsung jadi konten, B harus disebut belum pasti, C tidak diangkat.
    """

    A = 'A', 'A — catatan resmi'
    B = 'B', 'B — media berbadan hukum'
    C = 'C', 'C — blog / agregat'


class NewsItem(models.Model):
    """Satu berita dari satu penerbit."""

    # Nama penerbit apa adanya, mis. 'Sky Sports'.
    publisher = models.CharField(max_length=80)
    # Grup kepemilikan. INI YANG DIPAKAI MENGHITUNG KESEPAKATAN, bukan
    # `publisher` — Manchester Evening News, Mirror, Express, dan Daily Star
    # semuanya Reach plc. Menghitungnya sebagai empat sumber bikin angka
    # "4 sumber sepakat" bohong: itu satu ruang redaksi menerbitkan ulang.
    publisher_group = models.CharField(max_length=80)
    tier = models.CharField(max_length=1, choices=NewsSourceTier.choices)

    title = models.CharField(max_length=400)
    url = models.URLField(max_length=600, unique=True)
    published_at = models.DateTimeField(null=True, blank=True)
    author = models.CharField(max_length=160, blank=True)

    # Nama orang yang DIKUTIP di judul, mis. 'Romano' atau 'Ornstein'.
    #
    # Kenapa penting: mayoritas berita transfer MU adalah outlet-outlet yang
    # mengutip satu-dua wartawan yang sama. "6 sumber sepakat" dalam kasus itu
    # sebenarnya berarti "6 outlet mengutip 1 orang" — jauh lebih lemah
    # daripada 6 outlet yang masing-masing punya reporter sendiri.
    quoted_source = models.CharField(max_length=80, blank=True)

    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at', '-fetched_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['publisher_group']),
        ]

    def __str__(self):
        return f'[{self.tier}] {self.publisher}: {self.title[:60]}'
