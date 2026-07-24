from django.db import models


class Team(models.Model):
    api_football_id = models.PositiveIntegerField(unique=True)
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

    api_football_id = models.PositiveIntegerField(unique=True)
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
