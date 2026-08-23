"""Pangkas `RawPayload` yang udah nggak ada gunanya.

**Baca ini sebelum menjalankan dengan --apply.**

RawPayload itu prasyarat mode putar ulang (Tahap 6 handoff): satu payload
summary per laga adalah bahan buat memutar ulang laga lama dan ngecek apakah
urutan kartu pundit-nya keluar seperti seharusnya. Menghapusnya berarti laga
itu nggak bisa diputar ulang lagi, dan nariknya ulang butuh panggilan ke API
ESPN yang nggak resmi.

Jadi command ini SENGAJA konservatif. Waktu ditulis (23 Agu 2026) kondisinya:
tabel ini 57 MB dari database 119 MB, dan disk server masih 314 GB kosong —
nggak ada krisis ruang. Alatnya ada supaya siap dipakai kalau nanti perlu,
bukan supaya dijalankan sekarang.

**Kenapa BUKAN retensi berbasis umur.** `fetched_at` itu `auto_now`, jadi dia
nyatet penulisan TERAKHIR, bukan penangkapan pertama. Selama command ESPN
masih narik ulang semua laga tiap 10 menit, tiap payload keliatan berumur nol
selamanya — retensi umur nggak akan menghapus apa pun. Dan sesudah penyaring
inkremental dipasang, semuanya berhenti diperbarui di hari yang sama, jadi
seluruh tabel bakal jatuh ke ambang umur BERSAMAAN. Dua-duanya salah. Yang
dipakai di sini: yatim, lalu musim.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from matches.models import Match, MatchExternalRef, RawPayload

# Musim yang selalu dipertahankan, dihitung mundur dari musim terbaru yang ada
# di DB. Mode putar ulang paling masuk akal dipakai buat laga yang belum lama.
KEEP_SEASONS = 3


def _mb(b):
    return round((b or 0) / 1048576, 1)


class Command(BaseCommand):
    help = 'Pangkas RawPayload yatim dan payload laga musim lama.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true', help='Beneran hapus. Tanpa ini cuma dry run.'
        )
        parser.add_argument(
            '--keep-seasons', type=int, default=KEEP_SEASONS,
            help=f'Jumlah musim terbaru yang dipertahankan (default {KEEP_SEASONS}).',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        if not apply_changes:
            self.stdout.write(
                self.style.WARNING('DRY RUN — nggak ada yang dihapus. Tambahin --apply.\n')
            )

        self._ringkasan()

        yatim = self._cari_yatim()
        lama = self._cari_musim_lama(options['keep_seasons'])

        # Jangan dihitung dobel kalau sebuah payload masuk dua kategori.
        target_ids = {p.pk for p in yatim} | {p.pk for p in lama}
        if not target_ids:
            self.stdout.write(self.style.SUCCESS('\nNggak ada yang perlu dipangkas.'))
            return

        qs = RawPayload.objects.filter(pk__in=target_ids)
        besar = qs.aggregate(b=Sum('size_bytes'))['b']
        self.stdout.write(
            f'\nTotal: {len(target_ids)} baris, {_mb(besar)} MB (ukuran JSON mentah).'
        )

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING('Jalanin ulang pakai --apply kalau angkanya masuk akal.')
            )
            return

        dihapus, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f'{dihapus} baris dihapus.'))

    def _ringkasan(self):
        self.stdout.write('Isi RawPayload sekarang:')
        for r in (
            RawPayload.objects.values('source', 'kind')
            .annotate(n=Count('id'), b=Sum('size_bytes'))
            .order_by('-b')
        ):
            self.stdout.write(
                f"  {r['source']:<12} {r['kind']:<16} {r['n']:>5} baris  {_mb(r['b']):>7} MB"
            )

    def _cari_yatim(self):
        """Payload yang key-nya nggak nyambung ke Match mana pun lagi.

        Kejadian kalau laga digabung (merge_duplicates) atau dihapus — payload
        lamanya nggak nunjuk ke apa-apa dan nggak bisa dipakai putar ulang.
        """
        yatim = []
        for payload in RawPayload.objects.all().only('id', 'source', 'key', 'size_bytes'):
            if not str(payload.key).isdigit():
                continue
            ada = MatchExternalRef.objects.filter(
                source=payload.source, external_id=int(payload.key)
            ).exists()
            if not ada:
                yatim.append(payload)
        self.stdout.write(f'\nYatim (key nggak nyambung ke Match): {len(yatim)}')
        for p in yatim[:5]:
            self.stdout.write(f'  {p.source}/{p.kind} key={p.key}')
        return yatim

    def _cari_musim_lama(self, keep):
        musim = sorted(
            {s for s in Match.objects.values_list('season', flat=True) if s}, reverse=True
        )
        if len(musim) <= keep:
            self.stdout.write(
                f'\nMusim lama: nggak ada (cuma {len(musim)} musim di DB, '
                f'ambang {keep}).'
            )
            return []

        dipertahankan = set(musim[:keep])
        dibuang = [s for s in musim if s not in dipertahankan]

        # Cari external_id ESPN buat laga-laga musim lama.
        refs = MatchExternalRef.objects.filter(
            match__season__in=dibuang
        ).values_list('source', 'external_id')
        pasangan = {(s, str(i)) for s, i in refs}

        target = [
            p
            for p in RawPayload.objects.all().only('id', 'source', 'key', 'size_bytes')
            if (p.source, str(p.key)) in pasangan
        ]
        self.stdout.write(
            f'\nMusim lama (di luar {keep} musim terbaru {sorted(dipertahankan)}): '
            f'{len(target)} payload dari musim {dibuang}'
        )
        return target
