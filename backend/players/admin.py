from django.contrib import admin

from .models import Injury, Player, PlayerExternalRef, Team, TeamExternalRef


class TeamExternalRefInline(admin.TabularInline):
    model = TeamExternalRef
    extra = 0


class PlayerExternalRefInline(admin.TabularInline):
    model = PlayerExternalRef
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'is_manchester_united')
    search_fields = ('name', 'short_name', 'code')
    inlines = [TeamExternalRefInline]


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'position', 'nationality', 'on_loan', 'is_active')
    list_filter = ('position', 'team', 'on_loan', 'is_active')
    search_fields = ('name', 'first_name', 'last_name')
    inlines = [PlayerExternalRefInline]


@admin.register(Injury)
class InjuryAdmin(admin.ModelAdmin):
    list_display = ('player', 'reason', 'status', 'start_date', 'expected_return_date')
    list_filter = ('status',)
    search_fields = ('player__name', 'reason')
