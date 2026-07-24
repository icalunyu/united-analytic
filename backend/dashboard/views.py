from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from matches.models import Match
from players.models import Injury, Player

LIVE_STATUSES = [Match.Status.LIVE, Match.Status.HALFTIME]
FINISHED_STATUSES = [
    Match.Status.FINISHED,
    Match.Status.EXTRA_TIME,
    Match.Status.PENALTIES,
]

POSITION_GROUPS = [
    ('Kiper', ['GK']),
    ('Bek', ['CB', 'RB', 'LB']),
    ('Gelandang', ['CDM', 'CM', 'CAM']),
    ('Penyerang', ['WNG', 'CF']),
]


def mu_matches():
    return Match.objects.filter(
        Q(home_team__is_manchester_united=True) | Q(away_team__is_manchester_united=True)
    ).select_related('home_team', 'away_team')


def match_result(match):
    """Return 'W'/'D'/'L' dari sudut pandang MU, atau None kalau belum final."""
    if match.home_score is None or match.away_score is None:
        return None

    mu_is_home = match.home_team.is_manchester_united
    mu_score = match.home_score if mu_is_home else match.away_score
    opp_score = match.away_score if mu_is_home else match.home_score

    if mu_score > opp_score:
        return 'W'
    if mu_score < opp_score:
        return 'L'
    return 'D'


def annotate_result(match):
    match.mu_result = match_result(match)
    return match


def home(request):
    now = timezone.now()
    finished = list(
        mu_matches().filter(status__in=FINISHED_STATUSES).order_by('-kickoff_at')[:20]
    )
    for m in finished:
        annotate_result(m)

    wins = sum(1 for m in finished if m.mu_result == 'W')
    draws = sum(1 for m in finished if m.mu_result == 'D')
    losses = sum(1 for m in finished if m.mu_result == 'L')
    goals_for = 0
    goals_against = 0
    for m in finished:
        mu_is_home = m.home_team.is_manchester_united
        goals_for += (m.home_score if mu_is_home else m.away_score) or 0
        goals_against += (m.away_score if mu_is_home else m.home_score) or 0

    featured = (
        mu_matches().filter(status__in=LIVE_STATUSES).order_by('kickoff_at').first()
        or mu_matches().filter(kickoff_at__gte=now).order_by('kickoff_at').first()
    )

    upcoming = list(
        mu_matches().filter(kickoff_at__gte=now).exclude(pk=featured.pk if featured else None)
        .order_by('kickoff_at')[:5]
    )

    competitions_tracked = (
        mu_matches().exclude(league_name='').values_list('league_name', flat=True).distinct().count()
    )
    squad_size = Player.objects.filter(team__is_manchester_united=True, is_active=True).count()

    chronological = list(reversed(finished))
    chart_labels = []
    chart_goals_for = []
    chart_goals_against = []
    for m in chronological:
        mu_is_home = m.home_team.is_manchester_united
        opponent = m.away_team if mu_is_home else m.home_team
        chart_labels.append(opponent.short_name or opponent.name)
        chart_goals_for.append((m.home_score if mu_is_home else m.away_score) or 0)
        chart_goals_against.append((m.away_score if mu_is_home else m.home_score) or 0)

    context = {
        'active_nav': 'dashboard',
        'featured': featured,
        'is_featured_live': bool(featured and featured.status in LIVE_STATUSES),
        'upcoming': upcoming,
        'recent_form': list(reversed(finished[:5])),
        'heatmap': list(reversed(finished)),
        'stats': {
            'played': len(finished),
            'wins': wins,
            'draws': draws,
            'losses': losses,
            'goals_for': goals_for,
            'goals_against': goals_against,
            'win_pct': round(wins / len(finished) * 100) if finished else 0,
        },
        'competitions_tracked': competitions_tracked,
        'squad_size': squad_size,
        'chart_labels': chart_labels,
        'chart_goals_for': chart_goals_for,
        'chart_goals_against': chart_goals_against,
    }
    return render(request, 'dashboard/home.html', context)


def schedule(request):
    show_all = request.GET.get('all') == '1'
    qs = mu_matches()

    if show_all:
        matches = qs.order_by('-kickoff_at')[:100]
    else:
        now = timezone.now()
        matches = qs.filter(
            Q(status__in=LIVE_STATUSES) | Q(kickoff_at__gte=now)
        ).order_by('kickoff_at')

    matches = [annotate_result(m) for m in matches]

    return render(
        request,
        'dashboard/schedule.html',
        {'active_nav': 'schedule', 'matches': matches, 'show_all': show_all},
    )


def match_detail(request, match_id):
    match = get_object_or_404(
        mu_matches().prefetch_related(
            'events__team', 'events__player', 'events__assist_player', 'team_statistics__team'
        ),
        pk=match_id,
    )
    annotate_result(match)

    home_stats = next(
        (s for s in match.team_statistics.all() if s.team_id == match.home_team_id), None
    )
    away_stats = next(
        (s for s in match.team_statistics.all() if s.team_id == match.away_team_id), None
    )

    chart_stat_labels = []
    chart_home_values = []
    chart_away_values = []
    card_rows = []

    if home_stats and away_stats:
        chart_defs = [
            ('possession_pct', 'Penguasaan Bola (%)'),
            ('shots_total', 'Tembakan'),
            ('shots_on_target', 'Tembakan Tepat Sasaran'),
            ('corners', 'Tendangan Sudut'),
            ('passes_accurate', 'Operan Akurat'),
            ('fouls', 'Pelanggaran'),
            ('offsides', 'Offside'),
            ('saves', 'Penyelamatan Kiper'),
        ]
        for field, label in chart_defs:
            chart_stat_labels.append(label)
            chart_home_values.append(getattr(home_stats, field) or 0)
            chart_away_values.append(getattr(away_stats, field) or 0)

        card_rows = [
            ('Kartu Kuning', home_stats.yellow_cards, away_stats.yellow_cards),
            ('Kartu Merah', home_stats.red_cards, away_stats.red_cards),
        ]

    return render(
        request,
        'dashboard/match_detail.html',
        {
            'active_nav': 'schedule',
            'match': match,
            'events': match.events.all(),
            'has_stats': bool(home_stats and away_stats),
            'card_rows': card_rows,
            'chart_stat_labels': chart_stat_labels,
            'chart_home_values': chart_home_values,
            'chart_away_values': chart_away_values,
            'is_live': match.status in LIVE_STATUSES,
        },
    )


def squad(request):
    players = Player.objects.filter(team__is_manchester_united=True, is_active=True).order_by(
        'name'
    )
    groups = []
    for label, codes in POSITION_GROUPS:
        members = [p for p in players if p.position in codes]
        if members:
            groups.append({'label': label, 'players': members})

    others = [
        p for p in players if p.position not in [c for _, codes in POSITION_GROUPS for c in codes]
    ]
    if others:
        groups.append({'label': 'Lainnya', 'players': others})

    return render(
        request,
        'dashboard/squad.html',
        {'active_nav': 'squad', 'groups': groups, 'total': players.count()},
    )


def injuries(request):
    injury_qs = Injury.objects.filter(player__team__is_manchester_united=True).select_related(
        'player'
    )
    return render(
        request, 'dashboard/injuries.html', {'active_nav': 'injuries', 'injuries': injury_qs[:40]}
    )
