from django.contrib import admin

from .models import Match, MatchEvent


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        'home_team',
        'away_team',
        'kickoff_at',
        'status',
        'home_score',
        'away_score',
        'league_name',
    )
    list_filter = ('status', 'league_name', 'season')
    search_fields = ('home_team__name', 'away_team__name')


@admin.register(MatchEvent)
class MatchEventAdmin(admin.ModelAdmin):
    list_display = ('match', 'event_type', 'team', 'player', 'minute')
    list_filter = ('event_type',)
    search_fields = ('match__home_team__name', 'match__away_team__name', 'player__name')
