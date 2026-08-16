"""Gabungin row Player/Team duplikat yang telanjur kebikin sebelum matcher
nama diperbaiki (aksen nggak dilipat — 'Šeško' vs 'Sesko' ke-anggep 2 orang).

Default-nya DRY RUN: nggak nulis apa-apa, cuma nampilin rencananya. Harus
lewat --apply buat beneran ngubah data.

    python manage.py merge_duplicates                # lihat rencananya
    python manage.py merge_duplicates --apply        # eksekusi

Referensi FK di-enumerate dinamis dari _meta, bukan di-hardcode: mayoritas
FK ke Team itu CASCADE, jadi satu referensi kelewat = Match ikut kehapus pas
row duplikatnya dibuang.
"""

from collections import defaultdict

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from players.models import Player, Team
from players.name_utils import fold_accents, normalize_team_name


def player_group_key(player):
    """Kunci pengelompokan: (inisial depan, nama belakang) yang udah dilipat
    aksennya — persis logika player_identity_key, tapi dipanggil di sini biar
    jelas apa yang dijadiin dasar penggabungan."""
    words = [w for w in fold_accents(player.name).replace('.', ' ').split() if w]
    if not words:
        return None
    initial = words[0][0] if len(words) > 1 else ''
    return initial, words[-1]


class Command(BaseCommand):
    help = 'Gabungin Player/Team duplikat hasil bug pencocokan nama beraksen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Beneran tulis perubahan. Tanpa ini cuma dry run.',
        )
        parser.add_argument('--players-only', action='store_true')
        parser.add_argument('--teams-only', action='store_true')

    def handle(self, *args, **options):
        apply_changes = options['apply']
        do_teams = not options['players_only']
        do_players = not options['teams_only']

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING('DRY RUN — nggak ada yang ditulis. Tambahin --apply buat eksekusi.\n')
            )

        total = 0
        # Tim duluan: kalau 2 tim digabung, pemainnya pindah ke tim yang sama
        # dan baru kedeteksi sebagai duplikat di tahap pemain.
        if do_teams:
            total += self._merge_teams(apply_changes)
        if do_players:
            total += self._merge_players(apply_changes)

        if not total:
            self.stdout.write(self.style.SUCCESS('Nggak ada duplikat. Nggak ada yang perlu digabung.'))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f'\nSelesai. {total} row duplikat digabung.'))
        else:
            self.stdout.write(
                self.style.WARNING(f'\n{total} row bakal digabung. Jalanin ulang pakai --apply.')
            )

    # ------------------------------------------------------------------ teams

    def _merge_teams(self, apply_changes):
        groups = defaultdict(list)
        for team in Team.objects.all():
            key = normalize_team_name(team.name)
            if key:
                groups[key].append(team)

        merged = 0
        for key, teams in sorted(groups.items()):
            if len(teams) < 2:
                continue
            canonical, losers = self._pick_canonical(teams)
            self.stdout.write(f'TIM  {canonical.name!r} (id={canonical.pk})')
            for loser in losers:
                self.stdout.write(f'       <- {loser.name!r} (id={loser.pk})')
                if apply_changes:
                    self._absorb(loser, canonical)
                merged += 1
        return merged

    # ---------------------------------------------------------------- players

    def _merge_players(self, apply_changes):
        groups = defaultdict(list)
        skipped_no_team = 0
        for player in Player.objects.select_related('team'):
            key = player_group_key(player)
            if key is None:
                continue
            if player.team_id is None:
                # Sengaja nggak digabung: tanpa tim, 2 pemain beda klub yang
                # kebetulan senama bisa ketuker. Sama batasannya kayak
                # resolve_player yang selalu nyaring per tim.
                skipped_no_team += 1
                continue
            groups[(player.team_id, key)].append(player)

        merged = 0
        for (team_id, key), players in sorted(groups.items(), key=lambda x: str(x[0])):
            if len(players) < 2:
                continue
            canonical, losers = self._pick_canonical(players)
            self.stdout.write(
                f'PEMAIN {canonical.name!r} (id={canonical.pk}, tim={canonical.team})'
            )
            for loser in losers:
                self.stdout.write(f'         <- {loser.name!r} (id={loser.pk})')
                if apply_changes:
                    self._absorb(loser, canonical)
                merged += 1

        if skipped_no_team:
            self.stdout.write(
                self.style.WARNING(
                    f'\n{skipped_no_team} pemain tanpa tim dilewati (nggak aman digabung '
                    f'tanpa tim sebagai penyaring).'
                )
            )
        return merged

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _pick_canonical(candidates):
        """Yang dipertahanin: paling banyak external ref (paling nyambung ke
        provider), lalu paling lengkap datanya, lalu pk terkecil biar hasilnya
        stabil kalau command-nya dijalanin ulang."""

        def score(obj):
            refs = obj.external_refs.count()
            filled = sum(
                1
                for field in obj._meta.fields
                if field.name not in ('id', 'created_at', 'updated_at')
                and getattr(obj, field.attname, None) not in (None, '', False)
            )
            return (-refs, -filled, obj.pk)

        ordered = sorted(candidates, key=score)
        return ordered[0], ordered[1:]

    def _absorb(self, loser, canonical):
        """Pindahin semua yang nunjuk ke `loser` supaya nunjuk ke `canonical`,
        lalu hapus `loser`."""
        model = type(loser)
        with transaction.atomic():
            for rel in model._meta.related_objects:
                field_name = rel.field.name
                related_model = rel.related_model
                rows = related_model.objects.filter(**{field_name: loser})

                for row in rows:
                    setattr(row, field_name, canonical)
                    try:
                        # Savepoint per baris: bentrok unique constraint itu
                        # hal yang diharapkan (mis. dua row PlayerMatchStatistics
                        # buat match yang sama), bukan error fatal.
                        with transaction.atomic():
                            row.save(update_fields=[rel.field.attname])
                    except IntegrityError:
                        # canonical udah punya baris setara buat kunci yang
                        # sama — punya loser tinggal dibuang.
                        row.delete()

            self._drop_self_matches(loser, canonical)
            loser.delete()

    @staticmethod
    def _drop_self_matches(loser, canonical):
        """Kalau 2 tim yang digabung pernah ketemu satu sama lain, hasil
        penggabungannya jadi match lawan diri sendiri — itu artefak duplikasi,
        bukan pertandingan beneran."""
        if not isinstance(loser, Team):
            return
        Match = apps.get_model('matches', 'Match')
        Match.objects.filter(home_team=canonical, away_team=canonical).delete()
