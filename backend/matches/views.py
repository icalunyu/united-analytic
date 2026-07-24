from django.db.models import Q
from django.utils import timezone
from rest_framework import generics

from .models import Match
from .serializers import MatchDetailSerializer, MatchListSerializer


def mu_matches_queryset():
    return Match.objects.filter(
        Q(home_team__is_manchester_united=True) | Q(away_team__is_manchester_united=True)
    ).select_related('home_team', 'away_team')


class MatchListView(generics.ListAPIView):
    """GET /api/matches/

    Default: match yang lagi LIVE + jadwal MU berikutnya, urut terdekat dulu
    (match live selalu nongol duluan walaupun kickoff-nya udah lewat).
    Query params:
      - season: filter musim, contoh ?season=2024
      - all=true: tampilkan semua match (termasuk yang sudah lewat), urut terbaru dulu
    """

    serializer_class = MatchListSerializer

    # NB: Match.Status.EXTRA_TIME/PENALTIES di model ini artinya "match SUDAH
    # SELESAI lewat extra time/adu penalti" (mapping dari status historis
    # API-Football), bukan "lagi berlangsung" — jangan dimasukin ke sini.
    IN_PROGRESS_STATUSES = [
        Match.Status.LIVE,
        Match.Status.HALFTIME,
    ]

    def get_queryset(self):
        queryset = mu_matches_queryset()

        season = self.request.query_params.get('season')
        if season:
            queryset = queryset.filter(season=season)

        if self.request.query_params.get('all') == 'true':
            return queryset.order_by('-kickoff_at')

        return queryset.filter(
            Q(status__in=self.IN_PROGRESS_STATUSES) | Q(kickoff_at__gte=timezone.now())
        ).order_by('kickoff_at')


class MatchDetailView(generics.RetrieveAPIView):
    """GET /api/matches/<id>/ — detail match MU termasuk event-nya."""

    serializer_class = MatchDetailSerializer

    def get_queryset(self):
        return mu_matches_queryset().prefetch_related(
            'events__team', 'events__player', 'events__assist_player', 'team_statistics__team'
        )
