from django.db import models


class DataSource(models.TextChoices):
    """Sumber data eksternal yang bisa nge-supply Team/Match. Nambah provider
    baru cukup nambah 1 value di sini — nggak perlu migration schema baru."""

    API_FOOTBALL = 'api_football', 'API-Football'
    FOOTBALL_DATA = 'football_data', 'football-data.org'
    HIGHLIGHTLY = 'highlightly', 'Highlightly'
    THESPORTSDB = 'thesportsdb', 'TheSportsDB'
    ESPN = 'espn', 'ESPN'
    PREMIER_LEAGUE = 'premier_league', 'Premier League (PulseLive)'


class Team(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=50, blank=True)
    code = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=100, blank=True)
    founded = models.PositiveIntegerField(null=True, blank=True)
    logo_url = models.URLField(blank=True)
    is_manchester_united = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TeamExternalRef(models.Model):
    """Mapping (source, external_id) -> Team, biar 1 tim bisa punya ID beda
    di tiap provider tanpa duplikasi row Team."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='external_refs')
    source = models.CharField(max_length=30, choices=DataSource.choices)
    external_id = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'], name='unique_team_source_external_id'
            )
        ]

    def __str__(self):
        return f'{self.team.name} ({self.source}:{self.external_id})'


class Player(models.Model):
    class Position(models.TextChoices):
        GOALKEEPER = 'GK', 'Goalkeeper'
        CENTRE_BACK = 'CB', 'Centre-Back'
        RIGHT_BACK = 'RB', 'Right-Back'
        LEFT_BACK = 'LB', 'Left-Back'
        DEFENSIVE_MIDFIELD = 'CDM', 'Defensive Midfield'
        CENTRAL_MIDFIELD = 'CM', 'Central Midfield'
        ATTACKING_MIDFIELD = 'CAM', 'Attacking Midfield'
        WINGER = 'WNG', 'Winger'
        FORWARD = 'CF', 'Centre-Forward'

    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='players'
    )
    name = models.CharField(max_length=150)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    position = models.CharField(max_length=3, choices=Position.choices, blank=True)
    shirt_number = models.PositiveSmallIntegerField(null=True, blank=True)
    height_cm = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.PositiveSmallIntegerField(null=True, blank=True)
    photo_url = models.URLField(blank=True)
    on_loan = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PlayerExternalRef(models.Model):
    """Mapping (source, external_id) -> Player, sama pola kayak
    TeamExternalRef/MatchExternalRef."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='external_refs')
    source = models.CharField(max_length=30, choices=DataSource.choices)
    external_id = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'], name='unique_player_source_external_id'
            )
        ]

    def __str__(self):
        return f'{self.player.name} ({self.source}:{self.external_id})'


class Injury(models.Model):
    class Status(models.TextChoices):
        OUT = 'OUT', 'Out'
        DOUBTFUL = 'DOUBTFUL', 'Doubtful'
        RETURNED = 'RETURNED', 'Returned'

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='injuries')
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OUT)
    start_date = models.DateField()
    expected_return_date = models.DateField(null=True, blank=True)
    actual_return_date = models.DateField(null=True, blank=True)
    source_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.player.name} - {self.reason} ({self.status})'
