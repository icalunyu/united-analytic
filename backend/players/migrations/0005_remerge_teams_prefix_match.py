import re

from django.db import migrations

_SUFFIX_PATTERN = re.compile(r'\b(FC|CF|AFC|SC|CD|AC)\b\.?', re.IGNORECASE)
_NON_ALNUM_PATTERN = re.compile(r'[^a-z0-9\s]')
_WHITESPACE_PATTERN = re.compile(r'\s+')


def _normalize(name):
    name = _SUFFIX_PATTERN.sub('', name or '')
    name = name.lower()
    name = _NON_ALNUM_PATTERN.sub(' ', name)
    name = _WHITESPACE_PATTERN.sub(' ', name).strip()
    return name


def _names_match(name_a, name_b):
    norm_a = _normalize(name_a)
    norm_b = _normalize(name_b)
    if norm_a == norm_b:
        return True

    words_a = norm_a.split()
    words_b = norm_b.split()
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    if not shorter:
        return False

    return longer[: len(shorter)] == shorter


def forwards(apps, schema_editor):
    """Dedup susulan: matching sebelumnya (migration 0004 di app matches)
    cuma nyamain suffix FC/AFC/dll, belum nangkep kasus nama pendek vs nama
    resmi lengkap (mis. 'Brighton' vs 'Brighton & Hove Albion FC'). Di sini
    kita re-scan pakai matching prefix-kata yang lebih pintar."""
    Team = apps.get_model('players', 'Team')
    TeamExternalRef = apps.get_model('players', 'TeamExternalRef')
    Match = apps.get_model('matches', 'Match')
    Player = apps.get_model('players', 'Player')
    MatchEvent = apps.get_model('matches', 'MatchEvent')

    canonicals = []  # list of Team, urut dari id terkecil

    for team in Team.objects.all().order_by('id'):
        match_found = None
        for canonical in canonicals:
            if _names_match(canonical.name, team.name):
                match_found = canonical
                break

        if match_found is None:
            canonicals.append(team)
            continue

        canonical = match_found
        TeamExternalRef.objects.filter(team=team).update(team=canonical)
        Match.objects.filter(home_team=team).update(home_team=canonical)
        Match.objects.filter(away_team=team).update(away_team=canonical)
        Player.objects.filter(team=team).update(team=canonical)
        MatchEvent.objects.filter(team=team).update(team=canonical)

        if team.is_manchester_united and not canonical.is_manchester_united:
            canonical.is_manchester_united = True

        for field in ('short_name', 'code', 'country', 'founded', 'logo_url'):
            if not getattr(canonical, field) and getattr(team, field):
                setattr(canonical, field, getattr(team, field))

        canonical.save()
        team.delete()


def backwards(apps, schema_editor):
    pass  # dedup destruktif, nggak reversible dengan aman


class Migration(migrations.Migration):

    dependencies = [
        ('players', '0004_remove_team_api_football_id_and_more'),
        ('matches', '0005_remove_match_api_football_id_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
