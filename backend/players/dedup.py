from .models import Player, PlayerExternalRef, Team, TeamExternalRef
from .name_utils import player_names_match, team_names_match

_MERGEABLE_FIELDS = ('short_name', 'code', 'country', 'founded', 'logo_url')
_MERGEABLE_PLAYER_FIELDS = (
    'first_name',
    'last_name',
    'nationality',
    'birth_date',
    'position',
    'shirt_number',
    'height_cm',
    'weight_kg',
    'photo_url',
)


def resolve_team(source, external_id, defaults, cross_ref=None):
    """Cari Team berdasarkan (source, external_id).

    Kalau `cross_ref` dikasih (mis. `(DataSource.API_FOOTBALL, 33)` dari ID
    yang udah ke-embed di payload provider lain kayak TheSportsDB), itu
    dicoba duluan — jauh lebih akurat daripada cocokin nama. Kalau nggak
    ketemu/nggak dikasih, baru fallback ke matching nama (dedup lintas
    provider, termasuk kasus nama pendek vs nama resmi lengkap).

    Return (team, created).
    """
    ref = TeamExternalRef.objects.filter(source=source, external_id=external_id).first()
    if ref:
        _apply_updates(ref.team, defaults, fill_blank_only=False)
        return ref.team, False

    if cross_ref:
        cross_source, cross_external_id = cross_ref
        cross_ref_obj = TeamExternalRef.objects.filter(
            source=cross_source, external_id=cross_external_id
        ).first()
        if cross_ref_obj:
            TeamExternalRef.objects.create(
                team=cross_ref_obj.team, source=source, external_id=external_id
            )
            _apply_updates(cross_ref_obj.team, defaults, fill_blank_only=True)
            return cross_ref_obj.team, False

    incoming_name = defaults.get('name', '')
    existing = next(
        (team for team in Team.objects.all() if team_names_match(team.name, incoming_name)),
        None,
    )

    if existing:
        TeamExternalRef.objects.create(team=existing, source=source, external_id=external_id)
        _apply_updates(existing, defaults, fill_blank_only=True)
        return existing, False

    team = Team.objects.create(**defaults)
    TeamExternalRef.objects.create(team=team, source=source, external_id=external_id)
    return team, True


def _apply_updates(team, defaults, fill_blank_only):
    updates = {}

    if defaults.get('is_manchester_united') and not team.is_manchester_united:
        updates['is_manchester_united'] = True

    for field in _MERGEABLE_FIELDS:
        value = defaults.get(field)
        if not value:
            continue
        if fill_blank_only and getattr(team, field, None):
            continue
        updates[field] = value

    if updates:
        Team.objects.filter(pk=team.pk).update(**updates)
        team.refresh_from_db()


def resolve_player(source, external_id, defaults, team=None):
    """Cari Player berdasarkan (source, external_id). Kalau belum pernah
    ketemu, coba cocokin lewat nama belakang (dedup lintas provider) —
    dibatasi ke pemain di `team` yang sama kalau ada, biar nggak salah
    gabung ke pemain klub lain yang kebetulan nama belakangnya sama.

    Return (player, created).
    """
    ref = PlayerExternalRef.objects.filter(source=source, external_id=external_id).first()
    if ref:
        _apply_player_updates(ref.player, defaults, fill_blank_only=False)
        return ref.player, False

    incoming_name = defaults.get('name', '')
    candidates = Player.objects.filter(team=team) if team else Player.objects.all()
    existing = next(
        (player for player in candidates if player_names_match(player.name, incoming_name)),
        None,
    )

    if existing:
        PlayerExternalRef.objects.create(player=existing, source=source, external_id=external_id)
        _apply_player_updates(existing, defaults, fill_blank_only=True)
        return existing, False

    player = Player.objects.create(**defaults)
    PlayerExternalRef.objects.create(player=player, source=source, external_id=external_id)
    return player, True


def _apply_player_updates(player, defaults, fill_blank_only):
    updates = {}

    if defaults.get('team') and not player.team:
        updates['team'] = defaults['team']

    for field in _MERGEABLE_PLAYER_FIELDS:
        value = defaults.get(field)
        if not value:
            continue
        if fill_blank_only and getattr(player, field, None):
            continue
        updates[field] = value

    if updates:
        Player.objects.filter(pk=player.pk).update(**updates)
        player.refresh_from_db()
