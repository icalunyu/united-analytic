import re

from django.db import migrations

_SUFFIX_PATTERN = re.compile(r'\b(FC|CF|AFC|SC|CD|AC)\b\.?', re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r'\s+')


def _normalize_team_name(name):
    name = _SUFFIX_PATTERN.sub('', name or '')
    name = _WHITESPACE_PATTERN.sub(' ', name).strip()
    return name.lower()


def forwards(apps, schema_editor):
    Team = apps.get_model('players', 'Team')
    TeamExternalRef = apps.get_model('players', 'TeamExternalRef')
    Match = apps.get_model('matches', 'Match')
    MatchExternalRef = apps.get_model('matches', 'MatchExternalRef')
    Player = apps.get_model('players', 'Player')
    MatchEvent = apps.get_model('matches', 'MatchEvent')

    # 1) Backfill TeamExternalRef/MatchExternalRef dari field ID lama.
    for team in Team.objects.all():
        if team.api_football_id is not None:
            TeamExternalRef.objects.get_or_create(
                source='api_football', external_id=team.api_football_id, defaults={'team': team}
            )
        if team.football_data_id is not None:
            TeamExternalRef.objects.get_or_create(
                source='football_data', external_id=team.football_data_id, defaults={'team': team}
            )

    for match in Match.objects.all():
        if match.api_football_id is not None:
            MatchExternalRef.objects.get_or_create(
                source='api_football', external_id=match.api_football_id, defaults={'match': match}
            )
        if match.football_data_id is not None:
            MatchExternalRef.objects.get_or_create(
                source='football_data', external_id=match.football_data_id, defaults={'match': match}
            )

    # 2) Dedup Team berdasarkan normalized name (mis. "Everton" == "Everton FC"),
    # gabung semua row duplikat ke row dengan pk paling kecil (canonical).
    groups = {}
    for team in Team.objects.all().order_by('id'):
        key = _normalize_team_name(team.name)
        groups.setdefault(key, []).append(team)

    for teams in groups.values():
        if len(teams) <= 1:
            continue

        canonical = teams[0]
        for dupe in teams[1:]:
            TeamExternalRef.objects.filter(team=dupe).update(team=canonical)
            Match.objects.filter(home_team=dupe).update(home_team=canonical)
            Match.objects.filter(away_team=dupe).update(away_team=canonical)
            Player.objects.filter(team=dupe).update(team=canonical)
            MatchEvent.objects.filter(team=dupe).update(team=canonical)

            if dupe.is_manchester_united and not canonical.is_manchester_united:
                canonical.is_manchester_united = True

            for field in ('short_name', 'code', 'country', 'founded', 'logo_url'):
                if not getattr(canonical, field) and getattr(dupe, field):
                    setattr(canonical, field, getattr(dupe, field))

            canonical.save()
            dupe.delete()


def backwards(apps, schema_editor):
    # Dedup itu destruktif (row duplikat kehapus) — nggak reversible dengan aman.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0003_matchexternalref'),
        ('players', '0003_teamexternalref'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
