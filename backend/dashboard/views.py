from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from matches import (
    competitions,
    key_numbers,
    moments,
    prompts,
    ratings,
    report,
    scoreline,
    workload,
)
from players import availability
from players.provenance import describe_sources
from matches.lineup_prediction import MAKS_HIPOTESIS
from matches.models import (
    FieldConflict,
    HypothesisItem,
    Match,
    MatchEvent,
    MatchTeamStatistics,
    PlayerMatchStatistics,
    SavedMoment,
)
from matches.momentum import build_momentum
from players.models import (
    AvailabilityDecision,
    Injury,
    Player,
    PlayerAvailability,
    Team,
)

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
    """Return 'W'/'D'/'L' dari sudut pandang MU, atau None kalau belum final.

    Cuma penerusan ke `matches/scoreline.py`. Aturan "United selalu ditulis
    lebih dulu" ditulis sekali di sana supaya tiap halaman tidak menurunkan
    versinya sendiri — itu cara "2-1" berubah arti diam-diam antar kartu.
    """
    return scoreline.hasil(match)


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
        mu, lawan = scoreline.skor(m)
        goals_for += mu or 0
        goals_against += lawan or 0

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
        _, opponent, _ = scoreline.sudut_pandang(m)
        mu_gol, lawan_gol = scoreline.skor(m)
        chart_labels.append(opponent.short_name or opponent.name)
        chart_goals_for.append(mu_gol or 0)
        chart_goals_against.append(lawan_gol or 0)

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
    players = list(
        Player.objects.filter(team__is_manchester_united=True, is_active=True)
        .select_related('team')
        .order_by('name')
    )
    sekarang = timezone.now()

    # SQ-01 + SQ-02. Rekonsiliasinya di players/availability.py, bukan di sini,
    # karena aturan "siapa menang kalau dua sumber beda" harus bisa dites tanpa
    # menyalakan seluruh halaman.
    baris, konflik, laga_susunan = availability.rekonsiliasi(players, sekarang)

    # Beban 14 hari (LV-08). Rumusnya ditulis sekali di matches/workload.py
    # karena dirujuk tiga kartu berbeda: kolom ini, Kandidat Rotasi, dan
    # Duel Kunci.
    mu = Team.objects.filter(is_manchester_united=True).first()
    beban = {}
    if mu:
        beban = {
            r['player'].pk: r
            for r in workload.beban_skuad(mu, sekarang, pemain=players)
        }

    urutan = {kode: i for i, (_, codes) in enumerate(POSITION_GROUPS) for kode in codes}
    for r in baris:
        p = r['player']
        r['beban'] = beban.get(p.pk)
        r['urutan'] = (urutan.get(p.position, len(urutan)), p.name)
    baris.sort(key=lambda r: r['urutan'])

    return render(
        request,
        'dashboard/squad.html',
        {
            'active_nav': 'squad',
            'baris': baris,
            'konflik': konflik,
            'laga_susunan': laga_susunan,
            'total': len(players),
            'sumber_terpakai': [
                availability.label_sumber(s) for s in availability.sumber_terpakai(baris)
            ],
            'terakhir_diperbarui': availability.terakhir_diperbarui(baris),
            # Selalu tampilkan lima teratas, bukan cuma yang di atas ambang.
            # Kartu yang hilang waktu semua pemain aman bikin orang nggak bisa
            # bedain "nggak ada yang perlu diistirahatkan" dari "fiturnya
            # rusak" — dan desain LV-08 sendiri punya varian 'aman'.
            'beban_teratas': sorted(beban.values(), key=lambda x: -x['skor'])[:5],
            'ada_yang_perlu_diawasi': any(
                r['tingkat'] != 'aman' for r in beban.values()
            ),
            'jendela_hari': workload.JENDELA_HARI,
            'menit_patokan': workload.MENIT_PATOKAN,
        },
    )


@require_POST
def availability_decide(request, player_id):
    """Analis memenangkan satu sumber untuk satu pemain (aturan 3 di SQ-01)."""
    player = get_object_or_404(Player, pk=player_id, team__is_manchester_united=True)
    sumber = request.POST.get('sumber', '')
    entri = PlayerAvailability.objects.filter(player=player, source=sumber).first()
    if entri is None:
        return HttpResponseBadRequest(
            f'Sumber {sumber!r} nggak punya status buat {player.name}.'
        )
    AvailabilityDecision.objects.update_or_create(
        player=player,
        defaults={
            'source': sumber,
            # Status disalin, bukan cuma sumbernya — lihat alasannya di model.
            'status': entri.status,
            'note': (request.POST.get('catatan') or '')[:255],
        },
    )
    return redirect('dashboard:squad')


@require_POST
def availability_reset(request, player_id):
    AvailabilityDecision.objects.filter(player_id=player_id).delete()
    return redirect('dashboard:squad')


def injuries(request):
    injury_qs = Injury.objects.filter(player__team__is_manchester_united=True).select_related(
        'player'
    )
    return render(
        request, 'dashboard/injuries.html', {'active_nav': 'injuries', 'injuries': injury_qs[:40]}
    )


# ---------------------------------------------------------------- statistik

# Kolom tabel Statistik. `kunci` dipakai di URL buat sortir, `label` di header.
# `per90` menandai kolom yang dibagi menit — lihat catatan bias di
# `_agregat_pemain`.
KOLOM_STATISTIK = [
    {'kunci': 'nama', 'label': 'Pemain', 'per90': False, 'angka': False},
    {'kunci': 'pos', 'label': 'Pos', 'per90': False, 'angka': False},
    {'kunci': 'menit', 'label': 'Min', 'per90': False, 'angka': True},
    {'kunci': 'gol', 'label': 'G', 'per90': False, 'angka': True},
    {'kunci': 'assist', 'label': 'A', 'per90': False, 'angka': True},
    {'kunci': 'xg', 'label': 'xG', 'per90': False, 'angka': True},
    {'kunci': 'xa', 'label': 'xA', 'per90': False, 'angka': True},
    # Handoff minta 'Prog/90'. Metrik progresif TIDAK ADA di FotMob, Understat,
    # maupun ESPN — nol kemunculan 'prog'/'carries' di seluruh payload. Yang
    # paling dekat dan memang tersimpan adalah umpan ke sepertiga akhir, tapi
    # itu metrik BERBEDA dan labelnya harus jujur menyebut begitu.
    {'kunci': 'final3', 'label': '1/3 Akhir/90', 'per90': True, 'angka': True},
    {'kunci': 'umpan', 'label': 'Umpan%', 'per90': False, 'angka': True},
    {'kunci': 'intersep', 'label': 'Int/90', 'per90': True, 'angka': True},
    {'kunci': 'sv', 'label': 'Sv%', 'per90': False, 'angka': True},
]

# Handoff cuma minta dua chip musim: 2026/27 dan 2025/26.
MUSIM_STATISTIK = 2

# Menit minimum sebelum kolom per-90 ditampilkan. Di bawah ini penyebutnya
# terlalu kecil: 1 intersep dalam 8 menit jadi 11,3 per 90 dan langsung
# menclok di puncak tabel.
MENIT_MINIMUM_PER90 = 90

# Ambang sampel buat kolom PERSENTASE. Masalahnya sama tapi obatnya beda:
# persentase nggak dibagi menit, jadi ambang menit nggak nolong. Yang bikin
# 100% nggak berarti apa-apa itu penyebutnya — 1 umpan dari 1.
#
# Kejadian nyata waktu halaman ini pertama tayang: Bendito Mantato, 14 menit,
# nangkring di puncak Umpan% dengan 100%. Angkanya benar, tapi tabel yang
# menempatkan pemain 14 menit di atas Mainoo 1.623 menit itu menyesatkan —
# dan halaman ini dipakai buat ngutip angka pas siaran.
UMPAN_MINIMUM = 50   # umpan dicoba
SAVE_MINIMUM = 5     # tembakan yang beneran mengarah ke gawang


def _agregat_pemain(rows):
    """Ringkas baris per-laga jadi satu baris per pemain.

    **Penyebut per-90 sengaja BUKAN total menit pemain.** Di musim 2025 cuma
    566 dari 850 baris punya `minutes_played`, dan baris yang punya menit belum
    tentu sama dengan baris yang punya `interceptions`. Kalau totalnya dibagi
    total menit, tiap pemain kena bias yang BESARNYA BEDA-BEDA tergantung
    seberapa bolong datanya — dan yang rusak bukan skala kolomnya, tapi URUTAN
    SORTIR, justru fitur utama halaman ini.

    Jadi tiap metrik per-90 memakai menit dari laga yang metrik itu ADA.
    Konsekuensinya kolom Min (total) dan penyebut per-90 bisa berbeda, dan itu
    memang benar — keterangan di halaman menyebutkannya.
    """
    per_pemain = {}
    for r in rows:
        d = per_pemain.setdefault(
            r.player_id,
            {
                'player': r.player,
                'menit': 0, 'gol': 0, 'assist': 0,
                'xg': 0.0, 'xa': 0.0,
                'final3': 0, 'final3_menit': 0,
                'intersep': 0, 'intersep_menit': 0,
                'umpan_akurat': 0, 'umpan_total': 0,
                'saves': 0, 'kebobolan': 0, 'ada_kiper': False,
                'laga': 0,
                # Gabungan field_sources dari semua laga pemain ini. Dipakai
                # buat chip 'sumber: A+C' — prinsip desain no. 2, tiap angka
                # membawa sumbernya.
                'sumber': {},
            },
        )
        d['sumber'].update(r.field_sources or {})
        menit = r.minutes_played or 0
        d['menit'] += menit
        d['laga'] += 1
        d['gol'] += r.goals or 0
        d['assist'] += r.assists or 0
        d['xg'] += r.xg or 0.0
        d['xa'] += r.xa or 0.0
        if r.passes_into_final_third is not None:
            d['final3'] += r.passes_into_final_third
            d['final3_menit'] += menit
        if r.interceptions is not None:
            d['intersep'] += r.interceptions
            d['intersep_menit'] += menit
        if r.passes_total:
            d['umpan_akurat'] += r.passes_accurate or 0
            d['umpan_total'] += r.passes_total
        # HANYA kiper. ESPN nulis goals_conceded ke SEMUA baris pemain, bukan
        # cuma kiper — jadi tanpa pagar ini bek yang timnya kebobolan 2 dapat
        # Sv% = 0/(0+2) = 0,0%. Angka nol itu kelihatan seperti data padahal
        # omong kosong, dan itu jenis kesalahan yang nggak kelihatan salah.
        if (r.player.position or '') == 'GK':
            d['saves'] += r.saves or 0
            d['kebobolan'] += r.goals_conceded or 0
            d['ada_kiper'] = True
    return per_pemain


# Field mana yang menyusun tiap kolom — dipakai `describe_sources` buat
# bilang angka ini datang dari mana.
SUMBER_KOLOM = {
    'menit': ['minutes_played'],
    'gol': ['goals'],
    'assist': ['assists'],
    'xg': ['xg'],
    'xa': ['xa'],
    'final3': ['passes_into_final_third'],
    'umpan': ['passes_accurate', 'passes_total'],
    'intersep': ['interceptions'],
    'sv': ['saves', 'goals_conceded'],
}


def _per90(total, menit):
    if not menit or menit < MENIT_MINIMUM_PER90:
        return None
    return round(total / menit * 90, 2)


def statistics(request):
    """Basis data pemain: filter musim & kompetisi, kolom bisa disortir."""
    musim_tersedia = sorted(
        {
            s
            for s in Match.objects.filter(
                Q(home_team__is_manchester_united=True)
                | Q(away_team__is_manchester_united=True)
            ).values_list('season', flat=True)
            if s
        },
        reverse=True,
    )[:MUSIM_STATISTIK]

    musim = request.GET.get('musim')
    musim_aktif = int(musim) if musim and musim.isdigit() and int(musim) in musim_tersedia \
        else (musim_tersedia[0] if musim_tersedia else None)

    kompetisi = request.GET.get('kompetisi') or ''
    urut = request.GET.get('urut') or 'menit'
    naik = request.GET.get('arah') == 'naik'

    rows = (
        PlayerMatchStatistics.objects.filter(
            team__is_manchester_united=True, match__season=musim_aktif
        )
        .select_related('player')
    )
    if kompetisi in competitions.LABELS:
        rows = rows.filter(match__league_name__in=competitions.league_names_for(kompetisi))

    agregat = _agregat_pemain(rows)

    baris = []
    for d in agregat.values():
        baris.append({
            'nama': d['player'].name,
            'pos': d['player'].position or '-',
            'laga': d['laga'],
            'menit': d['menit'],
            'gol': d['gol'],
            'assist': d['assist'],
            'xg': round(d['xg'], 2) if d['xg'] else None,
            'xa': round(d['xa'], 2) if d['xa'] else None,
            'final3': _per90(d['final3'], d['final3_menit']),
            'umpan': (
                round(d['umpan_akurat'] / d['umpan_total'] * 100, 1)
                if d['umpan_total'] >= UMPAN_MINIMUM else None
            ),
            'intersep': _per90(d['intersep'], d['intersep_menit']),
            'sv': (
                round(d['saves'] / (d['saves'] + d['kebobolan']) * 100, 1)
                if d['ada_kiper'] and (d['saves'] + d['kebobolan']) >= SAVE_MINIMUM
                else None
            ),
            'sumber': describe_sources(
                d['sumber'], [f for fs in SUMBER_KOLOM.values() for f in fs]
            ),
        })

    # "Baris tanpa data SELALU di bawah, di kedua arah" — handoff. Ini nggak
    # bisa dicapai satu ORDER BY: kalau None ikut disortir, membalik arah bakal
    # melempar mereka ke atas. Jadi yang kosong dipisah DULU, yang berisi
    # disortir, lalu yang kosong ditempel di belakang — apa pun arahnya.
    if urut not in {k['kunci'] for k in KOLOM_STATISTIK}:
        urut = 'menit'
    berisi = [b for b in baris if b.get(urut) is not None]
    kosong = [b for b in baris if b.get(urut) is None]
    berisi.sort(
        key=lambda b: b[urut].lower() if isinstance(b[urut], str) else b[urut],
        reverse=not naik,
    )
    kosong.sort(key=lambda b: b['nama'].lower())
    baris = berisi + kosong

    # Konflik Sumber. Desain menaruh panel ini di halaman Skuad, TAPI yang
    # dimaksud di sana adalah konflik STATUS KETERSEDIAAN antar feed cedera —
    # dan itu masih terblokir karena cuma ada satu feed cedera.
    #
    # Yang kita PUNYA adalah konflik ANGKA STATISTIK antar provider, dan
    # tempatnya yang jujur ya di sini, di halaman yang menampilkan angka itu.
    # Menaruhnya di Skuad bakal bikin orang mengira itu konflik ketersediaan.
    konflik = list(
        FieldConflict.objects.filter(
            player__team__is_manchester_united=True, match__season=musim_aktif
        )
        .select_related('player', 'match__home_team', 'match__away_team')
        .order_by('-detected_at')[:8]
    )

    return render(
        request,
        'dashboard/statistics.html',
        {
            'active_nav': 'statistics',
            'konflik': konflik,
            'konflik_total': FieldConflict.objects.filter(
                player__team__is_manchester_united=True, match__season=musim_aktif
            ).count(),
            'kolom': KOLOM_STATISTIK,
            'baris': baris,
            'musim_tersedia': musim_tersedia,
            'musim_aktif': musim_aktif,
            'kompetisi_aktif': kompetisi,
            'kategori': [
                {'kunci': k, 'label': competitions.LABELS[k]}
                for k in competitions.ORDER
                if k != 'lainnya'
            ],
            'urut': urut,
            'naik': naik,
            'menit_minimum': MENIT_MINIMUM_PER90,
            'umpan_minimum': UMPAN_MINIMUM,
            'save_minimum': SAVE_MINIMUM,
        },
    )


# ------------------------------------------------------------------ pra laga

H2H_JUMLAH = 5


def pre_match(request):
    """Halaman Pra-laga: identitas laga, prediksi susunan, hipotesis, H2H.

    Dua mode, sesuai handoff:
    - **Menyiapkan laga** (belum kick-off) — prediksi masih diperbarui otomatis
      sampai peluit, dan tiap konten membawa cap waktu versinya.
    - **Laga berjalan · cek prediksi** — yang dibandingkan adalah prediksi
      TERAKHIR SEBELUM kick-off.

    Handoff melarang mekanisme kunci: *"Jangan menambahkan tombol lock, status
    'diperiksa oleh X', atau approval flow; app tidak punya login sehingga
    klaim itu tidak bisa dibuktikan."* Yang menegakkan kejujurannya bukan
    tombol, tapi `prediction_before_kickoff()` — dia menyaring
    `created_at < kickoff_at`, jadi apa pun yang ditulis sesudah peluit nggak
    bisa menyamar jadi prediksi pra-laga.
    """
    mu = Team.objects.filter(is_manchester_united=True).first()
    now = timezone.now()

    match_id = request.GET.get('match')
    if match_id and match_id.isdigit():
        match = Match.objects.filter(pk=int(match_id)).first()
    else:
        match = (
            mu_matches()
            .filter(Q(status__in=LIVE_STATUSES) | Q(kickoff_at__gte=now))
            .order_by('kickoff_at')
            .first()
        )

    if match is None:
        return render(request, 'dashboard/pre_match.html',
                      {'active_nav': 'pre_match', 'match': None})

    berjalan = match.status in LIVE_STATUSES
    selesai = match.status in FINISHED_STATUSES
    snapshot = match.prediction_before_kickoff()

    slots = []
    if snapshot:
        slots = list(
            snapshot.lineup_slots.select_related('player').order_by('slot')
        )
        for s in slots:
            # Orientasi tayangan televisi: tim menyerang ke KANAN, jadi kiper
            # di kiri dan bek kiri di ATAS. Koordinat FotMob sudah begitu —
            # x kecil = dekat gawang sendiri, y kecil = sisi kiri lapangan —
            # jadi dipetakan langsung tanpa dibalik.
            s.gaya = (
                f'left:{(s.pitch_x or 0.5) * 100:.1f}%;'
                f'top:{(s.pitch_y or 0.5) * 100:.1f}%'
            )

    # Head to Head: pertemuan terakhir lintas kompetisi.
    lawan = match.away_team if match.home_team_id == (mu.pk if mu else None) else match.home_team
    h2h = []
    if mu and lawan and lawan.pk != mu.pk:
        h2h = [
            annotate_result(m)
            for m in mu_matches()
            .filter(Q(home_team=lawan) | Q(away_team=lawan))
            .filter(status__in=FINISHED_STATUSES)
            .exclude(pk=match.pk)
            .order_by('-kickoff_at')[:H2H_JUMLAH]
        ]

    menang = sum(1 for m in h2h if m.mu_result == 'W')
    seri = sum(1 for m in h2h if m.mu_result == 'D')

    # PR-03. Kandidat dihasilkan mesin; yang DIPERTARUHKAN dipilih analis —
    # handoff: "App tidak menyimpulkan, dia menyiapkan bukti."
    semua = list(snapshot.hypotheses.all()) if snapshot else []
    dipertaruhkan = [h for h in semua if h.selected]
    kandidat = [h for h in semua if not h.selected]
    # Snapshot lama (sebelum kolom `selected` ada) tidak punya satu pun pilihan.
    # Menampilkannya sebagai panel kosong bikin data yang ada kelihatan hilang,
    # jadi seluruh isinya dianggap dipertaruhkan — apa adanya seperti dulu.
    if not dipertaruhkan and (berjalan or selesai):
        dipertaruhkan, kandidat = semua, []
    # Sesudah peluit, pilihannya beku: mengubah apa yang dipertaruhkan setelah
    # tahu hasilnya menghapus seluruh guna panel Cek Prediksi.
    bisa_dipilih = bool(snapshot) and not berjalan and not selesai

    return render(
        request,
        'dashboard/pre_match.html',
        {
            'active_nav': 'pre_match',
            'match': match,
            'lawan': lawan,
            'berjalan': berjalan,
            'selesai': selesai,
            'snapshot': snapshot,
            'slots': slots,
            'hipotesis': dipertaruhkan,
            'kandidat': kandidat,
            'maks_hipotesis': MAKS_HIPOTESIS,
            'kuota_penuh': len(dipertaruhkan) >= MAKS_HIPOTESIS,
            'bisa_dipilih': bisa_dipilih,
            'tolak_penuh': request.GET.get('penuh') == '1',
            'h2h': h2h,
            'h2h_menang': menang,
            'h2h_seri': seri,
            'h2h_kalah': len(h2h) - menang - seri,
            'mundur_hari': (match.kickoff_at - now).days if not selesai else None,
        },
    )


@require_POST
def hypothesis_toggle(request, item_id):
    """Analis memilih hipotesis mana yang dipertaruhkan (PR-03).

    Bukan approval flow yang dilarang handoff — tidak ada yang dikunci, tidak
    ada status "diperiksa oleh X", dan tidak ada login yang diklaim. Ini
    pilihan redaksional: kandidat mana yang naik jadi klaim. Handoff justru
    menuntutnya: *"Kesimpulan tetap dari analis."*
    """
    item = get_object_or_404(HypothesisItem.objects.select_related('snapshot__match'), pk=item_id)
    match = item.snapshot.match
    kembali = f"{reverse('dashboard:pre_match')}?match={match.pk}"

    if match.kickoff_at <= timezone.now():
        return HttpResponseBadRequest(
            'Laga sudah kick-off. Mengubah apa yang dipertaruhkan setelah tahu '
            'hasilnya menghapus seluruh guna panel Cek Prediksi.'
        )

    if not item.selected:
        sudah = item.snapshot.hypotheses.filter(selected=True).count()
        if sudah >= MAKS_HIPOTESIS:
            # Ditolak dengan alasan yang kelihatan di halaman, bukan 400 telanjang.
            return redirect(f'{kembali}&penuh=1')

    item.selected = not item.selected
    item.save(update_fields=['selected'])
    return redirect(kembali)


# ------------------------------------------------------------------- berita

BERITA_JUMLAH = 40
KESEPAKATAN_JAM = 48
KESEPAKATAN_MIN_GRUP = 2


def news(request):
    """Halaman Berita: umpan bertingkat + kesepakatan antar penerbit.

    Aturan redaksi dari handoff: **A boleh langsung jadi konten, B harus
    disebut belum pasti, C tidak diangkat.** Aturan itu ditulis di UI, bukan
    cuma di dokumen — kalau cuma di dokumen, ia nggak menolong siapa pun yang
    sedang buru-buru bikin konten.
    """
    from datetime import timedelta

    from news.feeds import nama_di_judul
    from news.models import NewsItem, NewsSourceTier

    tier = request.GET.get('tier') or ''
    item = NewsItem.objects.all()
    if tier in NewsSourceTier.values:
        item = item.filter(tier=tier)
    item = list(item[:BERITA_JUMLAH])

    # Kesepakatan dihitung per GRUP PENERBIT, bukan per artikel dan bukan per
    # penerbit. Reach plc memiliki MEN, Mirror, Express, dan Daily Star —
    # menghitungnya sebagai empat sumber bikin angkanya bohong: itu satu ruang
    # redaksi menerbitkan ulang.
    batas = timezone.now() - timedelta(hours=KESEPAKATAN_JAM)
    per_nama = {}
    for it in NewsItem.objects.filter(published_at__gte=batas):
        for nama in nama_di_judul(it.title):
            d = per_nama.setdefault(nama, {'grup': set(), 'item': [], 'dikutip': set()})
            d['grup'].add(it.publisher_group)
            d['item'].append(it)
            if it.quoted_source:
                d['dikutip'].add(it.quoted_source)

    kesepakatan = sorted(
        (
            {
                'nama': nama,
                'grup': sorted(d['grup']),
                'jumlah_grup': len(d['grup']),
                'jumlah_item': len(d['item']),
                'dikutip': sorted(d['dikutip']),
                'contoh': d['item'][0],
            }
            for nama, d in per_nama.items()
            if len(d['grup']) >= KESEPAKATAN_MIN_GRUP
        ),
        key=lambda x: (-x['jumlah_grup'], -x['jumlah_item']),
    )[:8]

    return render(
        request,
        'dashboard/news.html',
        {
            'active_nav': 'news',
            'item': item,
            'tier_aktif': tier,
            'tiers': NewsSourceTier.choices,
            'kesepakatan': kesepakatan,
            'jendela_jam': KESEPAKATAN_JAM,
            'total': NewsItem.objects.count(),
        },
    )


# ---------------------------------------------------------------- pasca laga

# Berapa laga yang muncul sebagai chip di PS-01. Bukan cuma laga terakhir —
# handoff eksplisit soal ini, karena bahan konten sering dibuat beberapa hari
# sesudah laganya lewat.
JUMLAH_CHIP_LAGA = 12

TIPE_KONTEN = prompts.TIPE
SUMBER_PROMPT = prompts.SUMBER
NADA_CAPTION = prompts.NADA


def _int_aman(nilai, bawaan=0):
    try:
        return int(nilai)
    except (TypeError, ValueError):
        return bawaan


def _pilih_laga(request):
    """(laga terpilih, daftar chip). Dipakai view utama dan handler POST."""
    daftar = list(
        mu_matches()
        .filter(status__in=FINISHED_STATUSES)
        .order_by('-kickoff_at')[:JUMLAH_CHIP_LAGA]
    )
    diminta = request.GET.get('laga') or request.POST.get('laga')
    if diminta:
        pilihan = next((m for m in daftar if str(m.pk) == str(diminta)), None)
        if pilihan is None:
            # Laga lama yang di luar 12 chip tetap boleh dibuka lewat URL —
            # kalau tidak, laporan laga musim lalu jadi mustahil dibuat.
            pilihan = (
                mu_matches().filter(pk=diminta, status__in=FINISHED_STATUSES).first()
            )
        if pilihan is not None:
            return pilihan, daftar
    return (daftar[0] if daftar else None), daftar


def post_match(request):
    match, daftar = _pilih_laga(request)
    if match is None:
        return render(
            request,
            'dashboard/post_match.html',
            {'active_nav': 'post_match', 'daftar': [], 'match': None},
        )

    mu_team, lawan_team, _ = scoreline.sudut_pandang(match)

    stats = list(
        PlayerMatchStatistics.objects.filter(match=match, team=mu_team).select_related('player')
    )
    nilai_pemain = ratings.nilai_skuad(stats)
    angka = key_numbers.untuk_laga(match)

    baris_tim = {b.team_id: b for b in MatchTeamStatistics.objects.filter(match=match)}
    baris_mu = baris_tim.get(mu_team.pk if mu_team else None)
    baris_lawan = baris_tim.get(lawan_team.pk if lawan_team else None)

    # PS-04: detektor dijalankan ulang pada data lengkap tiap halaman dibuka.
    # Menulis pada GET memang tidak lazim, tapi operasinya idempoten — momen
    # yang sama tidak pernah tersimpan dua kali (lihat constraint di model) —
    # dan alternatifnya (cron terpisah) bikin halaman menampilkan temuan basi
    # untuk laga yang baru saja datanya lengkap.
    moments.segarkan(
        match,
        moments.deteksi(match, baris_mu, baris_lawan, angka, nilai_pemain, stats),
    )
    momen = list(SavedMoment.objects.filter(match=match))

    gol = list(
        MatchEvent.objects.filter(match=match, event_type=MatchEvent.EventType.GOAL)
        .select_related('player', 'team')
        .order_by('minute', 'extra_minute')
    )
    gol_mu = [g for g in gol if g.team_id == (mu_team.pk if mu_team else None)]
    gol_lawan = [g for g in gol if g.team_id != (mu_team.pk if mu_team else None)]

    varian = _int_aman(request.GET.get('varian'), 0)
    laporan = report.susun(match, angka, nilai_pemain, gol_mu, gol_lawan, varian=varian)

    tipe = request.GET.get('tipe') if request.GET.get('tipe') in TIPE_KONTEN else 'carousel'
    sumber = (
        request.GET.get('sumber') if request.GET.get('sumber') in SUMBER_PROMPT else 'gabungan'
    )
    nada = request.GET.get('nada') if request.GET.get('nada') in NADA_CAPTION else 'analis'
    terpilih = [m for m in momen if m.selected]

    return render(
        request,
        'dashboard/post_match.html',
        {
            'active_nav': 'post_match',
            'match': match,
            'daftar': [
                {'match': m, 'teks': scoreline.ringkas(m)[0], 'tempat': scoreline.ringkas(m)[1]}
                for m in daftar
            ],
            'laporan': laporan,
            'laporan_teks': report.teks_polos(laporan),
            'varian_berikut': (varian + 1) % report.JUMLAH_VARIAN,
            'angka': angka,
            'min_sampel': key_numbers.MIN_SAMPEL,
            'nilai_pemain': nilai_pemain,
            'menit_sampel_kecil': ratings.MENIT_SAMPEL_KECIL,
            'momen': momen,
            'jumlah_terpilih': len(terpilih),
            'tipe': tipe,
            'sumber': sumber,
            'nada': nada,
            'tipe_pilihan': [(k, v['label']) for k, v in TIPE_KONTEN.items()],
            'sumber_pilihan': list(SUMBER_PROMPT.items()),
            'nada_pilihan': [(k, k.title()) for k in NADA_CAPTION],
            'prompt': prompts.susun(
                match, terpilih, angka, nilai_pemain, tipe=tipe, sumber=sumber
            ),
            'caption': prompts.caption(match, terpilih, angka, nada=nada),
        },
    )


def _kembali_ke_pasca(request, match_id):
    return redirect(f"{reverse('dashboard:post_match')}?laga={match_id}")


@require_POST
def moment_toggle(request, moment_id):
    """Centang / lepas centang — menentukan apa yang masuk prompt PS-05."""
    m = get_object_or_404(SavedMoment, pk=moment_id)
    m.selected = not m.selected
    m.save(update_fields=['selected'])
    return _kembali_ke_pasca(request, m.match_id)


@require_POST
def moment_add(request, match_id):
    match = get_object_or_404(Match, pk=match_id)
    teks = (request.POST.get('teks') or '').strip()
    if not teks:
        return HttpResponseBadRequest('Momen tanpa teks nggak bisa disimpan.')
    SavedMoment.objects.create(
        match=match,
        minute=_int_aman(request.POST.get('menit'), None) if request.POST.get('menit') else None,
        text=teks[:300],
        figure=(request.POST.get('angka') or '')[:60],
        origin=SavedMoment.Asal.ANALIS,
        origin_card='PS-04',
        selected=True,
    )
    return _kembali_ke_pasca(request, match.pk)


@require_POST
def moment_delete(request, moment_id):
    m = get_object_or_404(SavedMoment, pk=moment_id)
    match_id = m.match_id
    m.delete()
    return _kembali_ke_pasca(request, match_id)
