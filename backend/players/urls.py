from django.urls import path

from .views import InjuryListView, PlayerListView

urlpatterns = [
    path('players/', PlayerListView.as_view(), name='player-list'),
    path('injuries/', InjuryListView.as_view(), name='injury-list'),
]
