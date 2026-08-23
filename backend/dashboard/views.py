from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from matches import competitions
from matches.models import Match, MatchEvent
from matches.momentum import build_momentum
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


# Ikon per jenis event. Kartu dibedain kuning/merah lewat `detail` karena di
# model dua-duanya disimpen sebagai EventType.CARD.
_EVENT_ICONS = {
    MatchEvent.EventType.GOAL: '⚽',
    MatchEvent.EventType.SUBSTITUTION: '🔄',
    MatchEvent.EventType.VAR: '📺',
}


def _event_row(event, is_home):
    """Ubah 1 MatchEvent jadi baris timeline (ikon + teks utama + subteks)."""
    detail = event.detail or ''
    player = event.player.name if event.player else None

    if event.event_type == MatchEvent.EventType.GOAL:
        icon = '⚽'
        subtitle = f'assist: {event.assist_player.name}' if event.assist_player else ''
        # Varian gol ('Goal - Header', 'Penalty', 'Own Goal') informatif, tapi
        # 'Goal' polos nggak nambah apa-apa di sebelah ikon bola.
        if detail and detail != 'Goal' and len(detail) < 40:
            subtitle = f'{detail}{" · " + subtitle if subtitle else ""}'
    elif event.event_type == MatchEvent.EventType.CARD:
        icon = '🟥' if 'Red' in detail else '🟨'
        subtitle = detail
    elif event.event_type == MatchEvent.EventType.SUBSTITUTION:
        icon = '🔄'
        subtitle = f'← {event.assist_player.name}' if event.assist_player else ''
    else:
        icon = _EVENT_ICONS.get(event.event_type, '•')
        subtitle = detail if len(detail) < 40 else ''

    minute = f'{event.minute}'
    if event.extra_minute:
        minute += f'+{event.extra_minute}'

    return {
        'kind': 'event',
        'is_home': is_home,
        'minute': minute,
        'icon': icon,
        # Kalau nama pemain nggak ke-resolve, jatuh ke detail biar barisnya
        # nggak kosong melompong.
        'title': player or (detail[:40] if detail else '—'),
        'subtitle': subtitle,
        'is_mu': event.team.is_manchester_united,
    }


def build_timeline(match, events):
    """Susun event jadi baris timeline dua kolom (tim tuan rumah di kiri, tamu
    di kanan) ala scoreboard live: skor berjalan nempel di tiap gol, plus
    pemisah babak."""
    rows = []
    home_score = away_score = 0
    halftime_added = False

    for event in events:
        if not halftime_added and event.minute > 45:
            rows.append({'kind': 'divider', 'label': f'HT {home_score}-{away_score}'})
            halftime_added = True

        is_home = event.team_id == match.home_team_id
        row = _event_row(event, is_home)

        if event.event_type == MatchEvent.EventType.GOAL:
            # Gol bunuh diri tercatat atas nama tim si pencetak, tapi angkanya
            # masuk ke lawan.
            scored_for_home = not is_home if 'Own Goal' in (event.detail or '') else is_home
            if scored_for_home:
                home_score += 1
            else:
                away_score += 1
            row['score'] = f'{home_score}-{away_score}'

        rows.append(row)

    return rows


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


PER_HALAMAN = 25


def schedule(request):
    """Jadwal + arsip, bisa disaring per musim dan kompetisi.

    Dulu halaman ini cuma punya toggle `?all=1` yang motong di 100 laga
    terbaru. Sesudah backfill 8 musim ada 470 laga MU di DB, jadi ~370 di
    antaranya **nggak bisa dijangkau lewat UI sama sekali** — kerja backfill
    praktis nggak kelihatan.
    """
    musim = request.GET.get('musim') or ''
    kompetisi = request.GET.get('kompetisi') or ''
    menyaring = bool(musim or kompetisi or request.GET.get('all') == '1')

    qs = mu_matches()

    # Facet dihitung dari SELURUH laga MU, bukan dari hasil yang udah disaring —
    # supaya pilihan yang lagi aktif nggak menghilangkan pilihan lain.
    #
    # `.order_by()` kosong itu WAJIB, bukan gaya-gayaan: Match.Meta punya
    # `ordering = ['kickoff_at']`, dan Django nyeret kolom ordering itu ke
    # GROUP BY. Tanpa dikosongin, query ini balikin 288 baris (satu per
    # kickoff unik) bukan 8.
    musim_tersedia = [
        r['season']
        for r in qs.order_by().values('season').annotate(n=Count('id')).order_by('-season')
        if r['season']
    ]

    jumlah_per_kategori = {}
    for nama, n in qs.order_by().values_list('league_name').annotate(n=Count('id')):
        jumlah_per_kategori[competitions.classify(nama)] = (
            jumlah_per_kategori.get(competitions.classify(nama), 0) + n
        )
    kategori_tersedia = [
        {
            'kunci': k,
            'label': competitions.LABELS[k],
            'jumlah': jumlah_per_kategori[k],
        }
        for k in competitions.ORDER
        if jumlah_per_kategori.get(k)
    ]

    if musim.isdigit():
        qs = qs.filter(season=int(musim))
    if kompetisi in competitions.LABELS:
        qs = qs.filter(league_name__in=competitions.league_names_for(kompetisi))

    if menyaring:
        qs = qs.order_by('-kickoff_at')
    else:
        # Tampilan awal tetap seperti dulu: yang lagi jalan dan yang akan datang.
        qs = qs.filter(
            Q(status__in=LIVE_STATUSES) | Q(kickoff_at__gte=timezone.now())
        ).order_by('kickoff_at')

    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get('hal'))
    matches = [annotate_result(m) for m in halaman.object_list]

    return render(
        request,
        'dashboard/schedule.html',
        {
            'active_nav': 'schedule',
            'matches': matches,
            'halaman': halaman,
            'menyaring': menyaring,
            'musim_aktif': musim,
            'kompetisi_aktif': kompetisi,
            'musim_tersedia': musim_tersedia,
            'kategori_tersedia': kategori_tersedia,
            'total': halaman.paginator.count,
        },
    )


def build_momentum_markers(match, events):
    """Penanda gol & kartu buat ditempel di sepanjang sumbu waktu grafik
    momentum, biar kelihatan lonjakan tekanan mana yang berbuah gol."""
    markers = []
    for event in events:
        if event.event_type == MatchEvent.EventType.GOAL:
            icon = '⚽'
        elif event.event_type == MatchEvent.EventType.CARD:
            icon = '🟥' if 'Red' in (event.detail or '') else '🟨'
        else:
            continue

        markers.append(
            {
                'minute': event.minute,
                'icon': icon,
                'is_home': event.team_id == match.home_team_id,
                'label': f'{event.player.name if event.player else event.detail} {event.minute}\'',
            }
        )
    return markers


def match_detail(request, match_id):
    match = get_object_or_404(
        mu_matches().prefetch_related(
            'events__team',
            'events__player',
            'events__assist_player',
            'team_statistics__team',
            'plays__team',
        ),
        pk=match_id,
    )
    annotate_result(match)

    momentum = build_momentum(match, match.plays.all())
    momentum_max_minute = momentum[-1]['minute'] if momentum else 0

    # xG cuma ada buat match Premier League (cakupan Understat), jadi bagian
    # ini sengaja opsional — match cup tetep tampil normal tanpa xG.
    shots = list(match.shots.all())
    home_xg = sum(s.xg for s in shots if s.team_id == match.home_team_id)
    away_xg = sum(s.xg for s in shots if s.team_id == match.away_team_id)

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
            'timeline': build_timeline(match, match.events.all()),
            'momentum_minutes': [m['minute'] for m in momentum],
            'momentum_values': [m['value'] for m in momentum],
            'momentum_max_minute': momentum_max_minute,
            'momentum_markers': build_momentum_markers(match, match.events.all()),
            'has_xg': bool(shots),
            'home_xg': round(home_xg, 2),
            'away_xg': round(away_xg, 2),
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
