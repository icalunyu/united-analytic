from django.contrib import admin

from .models import Injury, Player, Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_football_id', 'country', 'is_manchester_united')
    search_fields = ('name', 'short_name', 'code')


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'position', 'nationality', 'on_loan', 'is_active')
    list_filter = ('position', 'team', 'on_loan', 'is_active')
    search_fields = ('name', 'first_name', 'last_name')


@admin.register(Injury)
class InjuryAdmin(admin.ModelAdmin):
    list_display = ('player', 'reason', 'status', 'start_date', 'expected_return_date')
    list_filter = ('status',)
    search_fields = ('player__name', 'reason')
