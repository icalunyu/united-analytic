from django.db import models

from players.models import DataSource, Player, Team


class Match(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = 'NS', 'Not Started'
        LIVE = 'LIVE', 'Live'
        HALFTIME = 'HT', 'Half Time'
        FINISHED = 'FT', 'Finished'
        POSTPONED = 'PST', 'Postponed'
        CANCELLED = 'CANC', 'Cancelled'
        EXTRA_TIME = 'AET', 'After Extra Time'
        PENALTIES = 'PEN', 'Penalties'

    league_id = models.PositiveIntegerField(null=True, blank=True)
    league_name = models.CharField(max_length=150, blank=True)
    season = models.PositiveSmallIntegerField(null=True, blank=True)
    round = models.CharField(max_length=100, blank=True)

    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_matches')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_matches')

    kickoff_at = models.DateTimeField()
    venue = models.CharField(max_length=150, blank=True)
    referee = models.CharField(max_length=150, blank=True)

    status = models.CharField(max_length=4, choices=Status.choices, default=Status.NOT_STARTED)
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['kickoff_at']

    def __str__(self):
        return f'{self.home_team} vs {self.away_team} ({self.kickoff_at:%Y-%m-%d})'


class MatchExternalRef(models.Model):
    """Mapping (source, external_id) -> Match, sama konsepnya kayak
    TeamExternalRef — biar 1 fixture nggak dobel row kalau ditarik dari
    lebih dari 1 provider."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='external_refs')
    source = models.CharField(max_length=30, choices=DataSource.choices)
    external_id = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'], name='unique_match_source_external_id'
            )
        ]

    def __str__(self):
        return f'{self.match} ({self.source}:{self.external_id})'


class MatchEvent(models.Model):
    class EventType(models.TextChoices):
        GOAL = 'GOAL', 'Goal'
        CARD = 'CARD', 'Card'
        SUBSTITUTION = 'SUBST', 'Substitution'
        VAR = 'VAR', 'VAR'

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='events')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='match_events')
    player = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True, related_name='match_events'
    )
    assist_player = models.ForeignKey(
        Player,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='match_event_assists',
    )

    event_type = models.CharField(max_length=5, choices=EventType.choices)
    detail = models.CharField(max_length=150, blank=True)
    minute = models.PositiveSmallIntegerField()
    extra_minute = models.PositiveSmallIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['minute', 'extra_minute']

    def __str__(self):
        return f'{self.match} - {self.get_event_type_display()} ({self.minute}\')'


class MatchTeamStatistics(models.Model):
    """Statistik teknis 1 tim buat 1 match (penguasaan bola, tembakan, dll).
    Berguna buat live pundit & post-match summary."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='team_statistics')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='match_statistics')

    possession_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_total = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_on_target = models.PositiveSmallIntegerField(null=True, blank=True)
    corners = models.PositiveSmallIntegerField(null=True, blank=True)
    fouls = models.PositiveSmallIntegerField(null=True, blank=True)
    offsides = models.PositiveSmallIntegerField(null=True, blank=True)
    yellow_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    red_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    passes_total = models.PositiveSmallIntegerField(null=True, blank=True)
    passes_accurate = models.PositiveSmallIntegerField(null=True, blank=True)
    saves = models.PositiveSmallIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['match', 'team'], name='unique_match_team_statistics')
        ]

    def __str__(self):
        return f'{self.match} - {self.team.name} stats'
