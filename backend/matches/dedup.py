from datetime import timedelta

from .models import Match, MatchExternalRef

_SAME_FIXTURE_WINDOW = timedelta(hours=12)


def resolve_match(source, external_id, home_team, away_team, kickoff_at, defaults):
    """Cari Match berdasarkan (source, external_id). Kalau belum pernah
    ketemu external_id ini, coba cocokin lewat home/away team + kickoff
    yang deket (dedup lintas provider) sebelum bikin row baru.

    Return (match, created).
    """
    ref = MatchExternalRef.objects.filter(source=source, external_id=external_id).first()
    if ref:
        Match.objects.filter(pk=ref.match_id).update(
            home_team=home_team, away_team=away_team, kickoff_at=kickoff_at, **defaults
        )
        ref.match.refresh_from_db()
        return ref.match, False

    existing = Match.objects.filter(
        home_team=home_team,
        away_team=away_team,
        kickoff_at__range=(kickoff_at - _SAME_FIXTURE_WINDOW, kickoff_at + _SAME_FIXTURE_WINDOW),
    ).first()

    if existing:
        MatchExternalRef.objects.create(match=existing, source=source, external_id=external_id)
        Match.objects.filter(pk=existing.pk).update(**defaults)
        existing.refresh_from_db()
        return existing, False

    match = Match.objects.create(
        home_team=home_team, away_team=away_team, kickoff_at=kickoff_at, **defaults
    )
    MatchExternalRef.objects.create(match=match, source=source, external_id=external_id)
    return match, True
