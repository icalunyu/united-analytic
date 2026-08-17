"""Bersihin row Player sampah bikinan parser commentary ESPN yang lama.

Dua bug di versi lama yang bikin ini:

1. Event di-parse pakai regex dari kalimat commentary, jadi potongan kalimat
   ikut kebaca sebagai nama pemain — 'Bruno Fernandes with a cross following
   a corner', 'Luke Shaw because of an injury'.
2. `_team_by_name` jatuh ke `home_team` tiap nama tim nggak cocok persis,
   jadi pemain lawan nempel ke tim tuan rumah. MU paling parah kena karena
   paling sering jadi tuan rumah.

Dua-duanya udah nggak ada di parser sekarang (baca `play.type` terstruktur,
dan `_team_by_name` balikin None kalau ragu), tapi row lamanya masih nyangkut.

Yang dianggap sampah: Player yang SEMUA external ref-nya dari
`espn_commentary`. Pemain yang beneran ada pasti kesentuh minimal 1 provider
lain (squad, fixtures, xG), jadi syarat ini nyaring cukup ketat.

Default DRY RUN. Harus --apply buat nulis.

    python manage.py clean_commentary_players
    python manage.py clean_commentary_players --apply
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from players.merge_utils import absorb
from players.models import DataSource, Player
from players.name_utils import player_identity_key

# Ekor kalimat yang kebawa ke "nama" pemain waktu parser lama motong teks
# commentary di tempat yang salah.
COMMENTARY_TAIL = re.compile(
    r'\s+(because of|with a|with an|following|after|from the|is shown|wins a|due to)\b.*$',
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = 'Bersihin Player sampah bikinan parser commentary ESPN yang lama.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true', help='Beneran tulis. Tanpa ini cuma dry run.'
        )
        parser.add_argument(
            '--limit', type=int, default=None, help='Batasi jumlah baris (buat tes).'
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        if not apply_changes:
            self.stdout.write(
                self.style.WARNING('DRY RUN — nggak ada yang ditulis. Tambahin --apply.\n')
            )

        canonical_index = self._build_canonical_index()
        candidates = self._find_candidates()
        if options['limit']:
            candidates = candidates[: options['limit']]

        self.stdout.write(f'{len(candidates)} row commentary-only ketemu.\n')

        merged = detached = ambiguous = 0
        for player in candidates:
            cleaned = COMMENTARY_TAIL.sub('', player.name).strip()
            targets = [
                t for t in canonical_index.get(player_identity_key(cleaned), []) if t.pk != player.pk
            ]

            if not targets:
                # Nggak ada pemain asli yang cocok. Row-nya nggak dihapus —
                # cuma dilepas dari timnya, biar nggak ngotorin daftar skuad
                # tapi event yang nunjuk ke dia tetep utuh.
                self.stdout.write(f'  LEPAS  {player.name!r} (id={player.pk}) — nggak ada padanan')
                if apply_changes:
                    Player.objects.filter(pk=player.pk).update(team=None)
                detached += 1
                continue

            teams = {t.team_id for t in targets}
            if len(teams) > 1:
                # Dua pemain asli beda tim punya kunci nama yang sama —
                # nebak di sini bisa naruh event ke orang yang salah.
                self.stdout.write(
                    self.style.WARNING(
                        f'  SKIP   {player.name!r} — ambigu, cocok ke {len(targets)} pemain di tim beda'
                    )
                )
                ambiguous += 1
                continue

            target = max(targets, key=lambda t: t.external_refs.count())
            note = '' if cleaned == player.name else f'  [ekor kalimat dipotong -> {cleaned!r}]'
            self.stdout.write(
                f'  GABUNG {player.name!r} (id={player.pk}) -> {target.name!r} '
                f'({target.team}){note}'
            )
            if apply_changes:
                absorb(player, target)
            merged += 1

        self._report(apply_changes, merged, detached, ambiguous)

    def _find_candidates(self):
        """Player yang punya ref espn_commentary dan NGGAK punya ref dari
        sumber lain.

        Yang timnya udah None dilewati: itu sisa run sebelumnya yang emang
        nggak punya padanan, dan udah nggak ngotorin daftar skuad — kalau
        ikut kejaring terus, command-nya nggak pernah kelihatan selesai.
        """
        return list(
            Player.objects.filter(external_refs__source=DataSource.ESPN_COMMENTARY)
            .exclude(team__isnull=True)
            .exclude(external_refs__source__in=[
                s for s in DataSource.values if s != DataSource.ESPN_COMMENTARY
            ])
            .distinct()
            .select_related('team')
        )

    def _build_canonical_index(self):
        """Peta kunci nama -> pemain 'asli' (yang kesentuh minimal 1 provider
        selain commentary)."""
        index = {}
        real = (
            Player.objects.exclude(external_refs__isnull=True)
            .filter(
                external_refs__source__in=[
                    s for s in DataSource.values if s != DataSource.ESPN_COMMENTARY
                ]
            )
            .distinct()
            .select_related('team')
        )
        for player in real:
            index.setdefault(player_identity_key(player.name), []).append(player)
        return index

    def _report(self, apply_changes, merged, detached, ambiguous):
        self.stdout.write('')
        summary = f'{merged} digabung, {detached} dilepas dari tim'
        if ambiguous:
            summary += f', {ambiguous} dilewati karena ambigu'

        if not (merged or detached or ambiguous):
            self.stdout.write(self.style.SUCCESS('Nggak ada yang perlu dibersihin.'))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f'Selesai. {summary}.'))
        else:
            self.stdout.write(self.style.WARNING(f'{summary}. Jalanin ulang pakai --apply.'))
