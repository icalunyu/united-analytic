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

    # Formasi awal, mis. '4-2-3-1'. Disimpen apa adanya sebagai teks karena
    # variasinya bebas dan cuma buat ditampilin, bukan buat di-query.
    home_formation = models.CharField(max_length=20, blank=True)
    away_formation = models.CharField(max_length=20, blank=True)

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

    # Statistik teknis lanjutan — bahan utama analisis kebutuhan transfer
    # (mis. rasio tekel/intersep buat nilai kebutuhan CDM).
    shots_blocked = models.PositiveSmallIntegerField(null=True, blank=True)
    crosses_total = models.PositiveSmallIntegerField(null=True, blank=True)
    crosses_accurate = models.PositiveSmallIntegerField(null=True, blank=True)
    long_balls_total = models.PositiveSmallIntegerField(null=True, blank=True)
    long_balls_accurate = models.PositiveSmallIntegerField(null=True, blank=True)
    tackles_total = models.PositiveSmallIntegerField(null=True, blank=True)
    tackles_won = models.PositiveSmallIntegerField(null=True, blank=True)
    interceptions = models.PositiveSmallIntegerField(null=True, blank=True)
    clearances_total = models.PositiveSmallIntegerField(null=True, blank=True)
    clearances_effective = models.PositiveSmallIntegerField(null=True, blank=True)
    penalty_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    penalty_shots = models.PositiveSmallIntegerField(null=True, blank=True)

    # Dari FotMob. Pemisahan umpan paruh sendiri/paruh lawan yang bikin PPDA
    # bisa dihitung — nggak ada provider gratis lain yang ngasih ini.
    passes_own_half = models.PositiveSmallIntegerField(null=True, blank=True)
    passes_opposition_half = models.PositiveSmallIntegerField(null=True, blank=True)
    touches_opp_box = models.PositiveSmallIntegerField(null=True, blank=True)
    big_chances = models.PositiveSmallIntegerField(null=True, blank=True)
    big_chances_missed = models.PositiveSmallIntegerField(null=True, blank=True)
    duels_won = models.PositiveSmallIntegerField(null=True, blank=True)
    dribbles_succeeded = models.PositiveSmallIntegerField(null=True, blank=True)

    xg = models.FloatField(null=True, blank=True)
    xg_open_play = models.FloatField(null=True, blank=True)
    xg_set_play = models.FloatField(null=True, blank=True)
    xg_non_penalty = models.FloatField(null=True, blank=True)
    xgot = models.FloatField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['match', 'team'], name='unique_match_team_statistics')
        ]

    def __str__(self):
        return f'{self.match} - {self.team.name} stats'

    # ESPN juga ngirim *Pct siap pakai, tapi cuma 1 angka desimal (0.8) —
    # dihitung ulang dari angka mentahnya jauh lebih presisi.
    @staticmethod
    def _ratio(accurate, total):
        if not total or accurate is None:
            return None
        return round(accurate / total * 100, 1)

    @property
    def pass_pct(self):
        return self._ratio(self.passes_accurate, self.passes_total)

    @property
    def cross_pct(self):
        return self._ratio(self.crosses_accurate, self.crosses_total)

    @property
    def long_ball_pct(self):
        return self._ratio(self.long_balls_accurate, self.long_balls_total)

    @property
    def tackle_pct(self):
        return self._ratio(self.tackles_won, self.tackles_total)


class PlayerMatchStatistics(models.Model):
    """Statistik 1 pemain di 1 match, plus posisinya di formasi awal.

    Ini fondasi buat analisis kebutuhan transfer per posisi — sebelumnya
    statistik cuma ada di level tim, jadi nggak bisa dipecah per pemain.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='player_statistics')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='match_statistics')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='player_match_statistics')

    starter = models.BooleanField(default=False)
    # Nomor urut posisi di formasi dari ESPN (1 = kiper). 0/None buat cadangan.
    #
    # HATI-HATI: nomor ini BUKAN urutan per baris. Di 4-2-3-1 milik MU, slot 4
    # itu Mainoo (gelandang) sementara slot 5 dan 6 Maguire dan Martínez (bek
    # tengah). Memetakan slot 2-5 sebagai bek empat menghasilkan formasi yang
    # salah. Buat menggambar formasi, pakai formation_x/formation_y.
    formation_place = models.PositiveSmallIntegerField(null=True, blank=True)

    # Posisi slot di diagram formasi, dari FotMob. Ternormalisasi 0..1:
    # x = kedalaman (0 = gawang sendiri, 1 = gawang lawan),
    # y = lebar lapangan.
    #
    # Ini posisi SLOT FORMASI, bukan posisi rata-rata pemain dari event —
    # jangan dilabeli "posisi rata-rata" di UI. Cuma terisi buat pemain yang
    # masuk starting eleven; cadangan nggak dapat koordinat.
    formation_x = models.FloatField(null=True, blank=True)
    formation_y = models.FloatField(null=True, blank=True)
    shirt_number = models.PositiveSmallIntegerField(null=True, blank=True)
    subbed_in = models.BooleanField(default=False)
    subbed_out = models.BooleanField(default=False)

    goals = models.PositiveSmallIntegerField(null=True, blank=True)
    assists = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_total = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_on_target = models.PositiveSmallIntegerField(null=True, blank=True)
    own_goals = models.PositiveSmallIntegerField(null=True, blank=True)
    fouls_committed = models.PositiveSmallIntegerField(null=True, blank=True)
    fouls_suffered = models.PositiveSmallIntegerField(null=True, blank=True)
    offsides = models.PositiveSmallIntegerField(null=True, blank=True)
    yellow_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    red_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    # Khusus kiper.
    saves = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_faced = models.PositiveSmallIntegerField(null=True, blank=True)
    goals_conceded = models.PositiveSmallIntegerField(null=True, blank=True)

    # Dari Understat — ESPN nggak punya satupun dari ini. xGChain/xGBuildup
    # ngukur kontribusi pemain ke rangkaian serangan, bukan cuma sentuhan
    # terakhir, jadi berguna buat nilai gelandang yang jarang cetak gol.
    minutes_played = models.PositiveSmallIntegerField(null=True, blank=True)
    xg = models.FloatField(null=True, blank=True)
    xa = models.FloatField(null=True, blank=True)
    xg_chain = models.FloatField(null=True, blank=True)
    xg_buildup = models.FloatField(null=True, blank=True)
    key_passes = models.PositiveSmallIntegerField(null=True, blank=True)

    # Dari FotMob. Ini yang paling nambah dibanding ESPN: aksi bertahan per
    # pemain sama sekali nggak ada di ESPN, padahal itu bahan buat nilai
    # kebutuhan posisi bertahan di analisis transfer.
    rating = models.FloatField(null=True, blank=True)
    touches = models.PositiveSmallIntegerField(null=True, blank=True)
    touches_opp_box = models.PositiveSmallIntegerField(null=True, blank=True)
    passes_accurate = models.PositiveSmallIntegerField(null=True, blank=True)
    passes_into_final_third = models.PositiveSmallIntegerField(null=True, blank=True)
    long_balls_accurate = models.PositiveSmallIntegerField(null=True, blank=True)
    dispossessed = models.PositiveSmallIntegerField(null=True, blank=True)
    chances_created = models.PositiveSmallIntegerField(null=True, blank=True)

    defensive_actions = models.PositiveSmallIntegerField(null=True, blank=True)
    tackles = models.PositiveSmallIntegerField(null=True, blank=True)
    blocks = models.PositiveSmallIntegerField(null=True, blank=True)
    clearances = models.PositiveSmallIntegerField(null=True, blank=True)
    interceptions = models.PositiveSmallIntegerField(null=True, blank=True)
    recoveries = models.PositiveSmallIntegerField(null=True, blank=True)
    dribbled_past = models.PositiveSmallIntegerField(null=True, blank=True)

    duels_won = models.PositiveSmallIntegerField(null=True, blank=True)
    duels_lost = models.PositiveSmallIntegerField(null=True, blank=True)
    ground_duels_won = models.PositiveSmallIntegerField(null=True, blank=True)
    aerial_duels_won = models.PositiveSmallIntegerField(null=True, blank=True)
    dribbles_succeeded = models.PositiveSmallIntegerField(null=True, blank=True)

    # Khusus kiper, dari FotMob.
    goals_prevented = models.FloatField(null=True, blank=True)
    xgot_faced = models.FloatField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-starter', 'formation_place']
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'player'], name='unique_player_match_statistics'
            )
        ]

    def __str__(self):
        return f'{self.player.name} - {self.match}'


class MatchPlay(models.Model):
    """Satu baris dari play-by-play ESPN — SEMUA kejadian, bukan cuma yang
    layak masuk timeline.

    Beda peran sama MatchEvent: MatchEvent itu kejadian penting yang
    ditampilin ke user (gol/kartu/substitusi), sementara MatchPlay nyimpen
    stream mentahnya (tembakan meleset, sepak pojok, pelanggaran, offside)
    yang dipakai buat ngitung momentum serangan. Dipisah biar timeline
    nggak kebanjiran 150-an baris pelanggaran.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='plays')
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True, related_name='match_plays'
    )
    player = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True, related_name='match_plays'
    )

    # ID play dari provider. Wajib: ESPN ngirim play yang sama berkali-kali
    # dengan `sequence` beda-beda (96 entri commentary cuma 60 play unik),
    # jadi cuma ID ini yang bisa dipakai buat dedup.
    external_id = models.CharField(max_length=40)

    # Slug mentah dari ESPN ('shot-on-target', 'corner-awarded', ...).
    # Sengaja nggak pakai TextChoices: ESPN bisa nambah slug baru kapan aja
    # dan kita nggak mau baris kebuang cuma gara-gara jenisnya belum kedaftar.
    play_type = models.CharField(max_length=60)
    text = models.TextField(blank=True)

    minute = models.PositiveSmallIntegerField()
    extra_minute = models.PositiveSmallIntegerField(null=True, blank=True)
    period = models.PositiveSmallIntegerField(null=True, blank=True)
    sequence = models.PositiveIntegerField(null=True, blank=True)

    # Posisi kejadian di lapangan, 0..1 relatif ke gawang yang diserang.
    field_x = models.FloatField(null=True, blank=True)
    field_y = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['minute', 'extra_minute', 'sequence']
        indexes = [models.Index(fields=['match', 'minute'])]
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'external_id'], name='unique_match_play_external_id'
            )
        ]

    def __str__(self):
        return f'{self.match} - {self.play_type} ({self.minute}\')'


class MatchShot(models.Model):
    """Satu tembakan berikut nilai xG-nya (sumber: Understat).

    Dipisah dari MatchPlay karena isinya beda sumber dan beda grain: MatchPlay
    itu play-by-play ESPN tanpa xG, ini khusus tembakan dengan xG + koordinat
    presisi. Dua-duanya bisa hidup bareng buat 1 match.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='shots')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='match_shots')
    player = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True, related_name='shots'
    )
    assisted_by = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True, related_name='shot_assists'
    )

    # Understat dan FotMob dua-duanya punya shotmap, dan keduanya disimpen —
    # skala koordinatnya beda (Understat 0..1, FotMob 0..100) jadi jangan
    # dicampur dalam satu perhitungan tanpa dinormalisasi dulu.
    source = models.CharField(max_length=30, choices=DataSource.choices)
    external_id = models.CharField(max_length=40)
    minute = models.PositiveSmallIntegerField()
    xg = models.FloatField()
    # Hasil tembakan: Goal, SavedShot, BlockedShot, MissedShots, ShotOnPost,
    # OwnGoal. Disimpen apa adanya dari provider.
    result = models.CharField(max_length=30)
    situation = models.CharField(max_length=30, blank=True)
    shot_type = models.CharField(max_length=30, blank=True)
    last_action = models.CharField(max_length=40, blank=True)

    # Posisi tembakan. Skalanya ikut provider (lihat catatan di `source`).
    x = models.FloatField(null=True, blank=True)
    y = models.FloatField(null=True, blank=True)

    # Cuma dari FotMob. xGOT ngukur kualitas eksekusi (seberapa bagus arah
    # tembakannya), beda dari xG yang ngukur kualitas peluangnya.
    xgot = models.FloatField(null=True, blank=True)
    is_on_target = models.BooleanField(null=True, blank=True)
    is_blocked = models.BooleanField(null=True, blank=True)
    is_from_inside_box = models.BooleanField(null=True, blank=True)
    # Titik lintasan bola di bidang gawang — buat gambar peta mulut gawang.
    goal_crossed_y = models.FloatField(null=True, blank=True)
    goal_crossed_z = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['minute']
        indexes = [models.Index(fields=['match', 'minute'])]
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'], name='unique_shot_source_external_id'
            )
        ]

    def __str__(self):
        return f'{self.match} - {self.player} {self.minute}\' (xG {self.xg:.2f})'


class MatchMomentum(models.Model):
    """Kurva momentum per menit dari provider.

    Model kita sendiri (matches/momentum.py) tetep yang dipakai buat tampilan,
    karena jalan di semua kompetisi. Yang ini disimpen sebagai pembanding buat
    nyetel bobot — dan sebagai cadangan di kompetisi yang play-by-play ESPN-nya
    terlalu jarang buat dihitung sendiri.

    Nilai bertanda: positif = tim tuan rumah menekan, negatif = tim tamu.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='momentum_points')
    source = models.CharField(max_length=30, choices=DataSource.choices)
    # Float, bukan integer: FotMob pakai menit pecahan buat injury time
    # (90.25, 90.5, 90.75). Dibulatkan, titik-titik itu nabrak jadi satu.
    minute = models.FloatField()
    value = models.FloatField()

    class Meta:
        ordering = ['minute']
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'source', 'minute'], name='unique_match_source_minute_momentum'
            )
        ]

    def __str__(self):
        return f'{self.match} - {self.source} {self.minute}\': {self.value}'
