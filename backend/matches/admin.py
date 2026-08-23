from django.contrib import admin

from .models import (
    HypothesisItem,
    LineupSlot,
    Match,
    MatchEvent,
    MatchExternalRef,
    PredictionSnapshot,
)


class MatchExternalRefInline(admin.TabularInline):
    model = MatchExternalRef
    extra = 0


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
    inlines = [MatchExternalRefInline]


@admin.register(MatchEvent)
class MatchEventAdmin(admin.ModelAdmin):
    list_display = ('match', 'event_type', 'team', 'player', 'minute')
    list_filter = ('event_type',)
    search_fields = ('match__home_team__name', 'match__away_team__name', 'player__name')


class HypothesisItemInline(admin.TabularInline):
    model = HypothesisItem
    extra = 3  # desain minta tiga kartu hipotesis per laga
    fields = ('order', 'text', 'evidence_note', 'outcome', 'outcome_note')


class LineupSlotInline(admin.TabularInline):
    model = LineupSlot
    extra = 11  # satu susunan penuh
    fields = ('slot', 'position', 'player', 'confidence_pct', 'is_key')
    autocomplete_fields = ('player',)


@admin.register(PredictionSnapshot)
class PredictionSnapshotAdmin(admin.ModelAdmin):
    """Tempat analis mengisi prediksi sebelum kick-off.

    Sengaja TIDAK ada tombol kunci — handoff melarangnya. Yang membuat cap
    waktunya bermakna adalah kebiasaan: tiap pembaruan bikin snapshot BARU,
    bukan mengedit yang lama. Kolom `sebelum_kickoff` dan `jeda_ke_kickoff` ada
    supaya analis langsung lihat apakah versi yang dibuka masih memenuhi syarat
    untuk dipakai Cek Prediksi.
    """

    list_display = ('match', 'created_at', 'sebelum_kickoff', 'jeda_ke_kickoff', 'ringkas')
    list_filter = ('match__season', 'match__league_name')
    search_fields = ('match__home_team__name', 'match__away_team__name', 'note')
    autocomplete_fields = ('match',)
    readonly_fields = ('created_at',)
    inlines = [HypothesisItemInline, LineupSlotInline]

    @admin.display(boolean=True, description='Sebelum kick-off?')
    def sebelum_kickoff(self, obj):
        return obj.before_kickoff

    @admin.display(description='Jeda ke kick-off')
    def jeda_ke_kickoff(self, obj):
        selisih = obj.lead_time
        jam = int(selisih.total_seconds() // 3600)
        if jam >= 0:
            return f'{jam} jam sebelum'
        return f'{abs(jam)} jam SESUDAH peluit'

    @admin.display(description='Isi')
    def ringkas(self, obj):
        return f'{obj.hypotheses.count()} hipotesis, {obj.lineup_slots.count()} slot'
