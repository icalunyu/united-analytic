from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from .models import Injury, Player
from .serializers import InjurySerializer, PlayerSerializer


class SquadPagination(PageNumberPagination):
    # Skuad sekitar 40-60 pemain — biar selalu muat 1 fetch, bukan kepotong
    # pagination default 25.
    page_size = 100


class PlayerListView(generics.ListAPIView):
    """GET /api/players/ — skuad MU.

    Query params:
      - position: filter posisi, contoh ?position=CB
      - all=true: termasuk pemain non-aktif (default cuma yang is_active)
    """

    serializer_class = PlayerSerializer
    pagination_class = SquadPagination

    def get_queryset(self):
        queryset = Player.objects.filter(team__is_manchester_united=True)

        if self.request.query_params.get('all') != 'true':
            queryset = queryset.filter(is_active=True)

        position = self.request.query_params.get('position')
        if position:
            queryset = queryset.filter(position=position.upper())

        return queryset


class InjuryListView(generics.ListAPIView):
    """GET /api/injuries/ — riwayat cedera pemain MU, terbaru dulu.

    Query params:
      - player: filter sebagian nama pemain
      - status: OUT, DOUBTFUL, atau RETURNED
    """

    serializer_class = InjurySerializer

    def get_queryset(self):
        queryset = Injury.objects.filter(player__team__is_manchester_united=True)

        player = self.request.query_params.get('player')
        if player:
            queryset = queryset.filter(player__name__icontains=player)

        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status.upper())

        return queryset
