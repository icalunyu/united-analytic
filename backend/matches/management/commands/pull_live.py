"""Penarikan mode live: sering waktu ada laga, diam total waktu tidak ada.

Masalah yang dipecahkan: `pull_match_events_espn` menyapu **delapan** slug
kompetisi dan makan ~9 detik per run, jadi dia dijadwalkan tiap 10 menit
malam hari. Waktu nonton laga, angka yang basi sepuluh menit itu terasa
seperti app-nya rusak.

Yang bikin polling cepat jadi mungkin bukan menambah kuota, tapi **membuang
pekerjaan yang tidak perlu**:

1. Kalau tidak ada laga MU yang sedang berjalan, command ini keluar dengan
   **nol panggilan jaringan**. Query-nya cuma satu, ke DB sendiri.
2. Kalau ada, dia cuma menembak slug kompetisi laga itu — satu, bukan delapan.

Hasilnya tiap dua menit selama laga jauh lebih ringan buat ESPN daripada
jadwal sepuluh menit yang sekarang, karena yang sekarang menembak tujuh
kompetisi yang jelas-jelas tidak sedang bermain.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from matches import live
from matches.competitions import espn_slug


class Command(BaseCommand):
    help = (
        'Tarik ulang laga MU yang sedang berjalan. Nol panggilan jaringan '
        'kalau nggak ada laga, jadi aman dijadwalkan tiap beberapa menit.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Tampilkan apa yang bakal ditarik tanpa menyentuh jaringan.',
        )

    def handle(self, *args, **options):
        sekarang = timezone.now()
        laga = live.laga_berjalan(sekarang)

        if not laga:
            self.stdout.write('Nggak ada laga MU yang berjalan. Nol panggilan jaringan.')
            return

        for m in laga:
            menit = int((sekarang - m.kickoff_at).total_seconds() // 60)
            posisi = f'menit ~{menit}' if menit >= 0 else f'{-menit} menit lagi'
            self.stdout.write(f'BERJALAN: {m} · {m.league_name} · {posisi} · status={m.status}')

        slugs, tanpa_slug = live.slug_yang_perlu(laga, espn_slug)

        for m in tanpa_slug:
            # Disebut, bukan didiamkan: kompetisi baru yang belum dipetakan
            # bikin mode live diam tanpa gejala kalau nggak dilaporkan.
            self.stderr.write(
                f'Kompetisi {m.league_name!r} belum punya slug ESPN — laga ini '
                f'nggak ikut ditarik. Tambahkan di matches/competitions.py.'
            )

        if not slugs:
            return

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(f'Dry run — bakal narik slug: {", ".join(slugs)}')
            )
            return

        for slug in slugs:
            self.stdout.write(f'--- menarik {slug} ---')
            call_command('pull_match_events_espn', slug=slug)
