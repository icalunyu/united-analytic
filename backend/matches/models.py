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

    def prediction_before_kickoff(self):
        """Versi prediksi TERAKHIR yang dibuat sebelum peluit, atau None.

        Ini satu-satunya sumber yang boleh dipakai panel Cek Prediksi. Filternya
        `created_at < kickoff_at`, jadi versi yang ditulis setelah laga mulai
        tidak bisa menyamar jadi prediksi pra-laga — tanpa perlu mekanisme
        kunci yang dilarang handoff.

        Memenuhi kriteria selesai Tahap 5: "prediksi untuk laga yang sudah
        berlangsung bisa diambil kembali beserta waktu pembuatannya."
        """
        return (
            self.prediction_snapshots.filter(created_at__lt=self.kickoff_at)
            .order_by('-created_at')
            .first()
        )


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

    # Peta {nama_field: kode_sumber}. Prinsip kedua design handoff: setiap
    # angka membawa sumbernya. Tanpa ini, satu baris bisa berisi xG dari
    # Understat dan tekel dari FotMob tanpa ada yang tahu mana dari mana —
    # dan provider yang jalan terakhir diam-diam menimpa yang lain.
    # Pengisian & prioritasnya diatur di players/provenance.py.
    field_sources = models.JSONField(default=dict, blank=True)

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
    # FotMob ngirim umpan pemain sebagai PECAHAN dalam satu kunci:
    #   {"key": "accurate_passes", "stat": {"type": "fractionWithPercentage",
    #                                       "total": 78, "value": 72}}
    # `value` itu umpan akurat, `total` umpan yang dicoba. Parser lama cuma
    # baca `value`, jadi penyebutnya kebuang dan Umpan% per pemain nggak bisa
    # dihitung sama sekali — padahal angkanya ada di payload dari awal.
    #
    # NB: level TIM formatnya beda ('321 (84%)' plus kunci `passes` terpisah),
    # jadi jangan samain parsernya.
    passes_total = models.PositiveSmallIntegerField(null=True, blank=True)
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

    # Peta {nama_field: kode_sumber}. Prinsip kedua design handoff: setiap
    # angka membawa sumbernya. Tanpa ini, satu baris bisa berisi xG dari
    # Understat dan tekel dari FotMob tanpa ada yang tahu mana dari mana —
    # dan provider yang jalan terakhir diam-diam menimpa yang lain.
    # Pengisian & prioritasnya diatur di players/provenance.py.
    field_sources = models.JSONField(default=dict, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-starter', 'formation_place']
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'player'], name='unique_player_match_statistics'
            )
        ]

    # ------------------------------------------------------------ turunan

    @staticmethod
    def _ratio(bagian, total):
        if not total or bagian is None:
            return None
        return round(bagian / total * 100, 1)

    @property
    def pass_pct(self):
        return self._ratio(self.passes_accurate, self.passes_total)

    @property
    def save_pct(self):
        """Persentase penyelamatan kiper.

        Penyebutnya `saves + goals_conceded`, BUKAN `shots_faced`. Ini bukan
        selera — `shots_faced` dari ESPN artinya SELURUH tembakan ke arah
        gawang termasuk yang melenceng, jadi dia penyebut yang salah: dari 500
        baris berkoordinat, **492 punya shots_faced != saves + kebobolan**.
        Contoh nyata: Onana shots_faced=7, saves=2, kebobolan=3 — kalau dibagi
        7 hasilnya 29%, padahal dari tembakan yang benar-benar mengarah ke
        gawang dia menyelamatkan 2 dari 5 alias 40%.

        Lagipula ESPN berhenti mengirim angka itu: seluruh baris musim 2025
        dan 2026 bernilai 0.

        None kalau penyebutnya 0 — kiper cadangan yang nggak main bukan berarti
        punya Sv% 0% (atau 100%). Di produksi ada 545 baris begitu.
        """
        total = (self.saves or 0) + (self.goals_conceded or 0)
        if not total or self.saves is None:
            return None
        return round(self.saves / total * 100, 1)

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


class MatchIngest(models.Model):
    """Catatan bahwa 1 laga udah ditarik dari 1 provider.

    Kenapa perlu: laga yang udah kelar datanya final, tapi command penarikan
    dulu narik ulang SEMUA laga selesai tiap kali jalan. Buat 46 laga itu
    boros; buat 380 laga se-liga itu jadi ratusan panggilan per malam ke API
    yang nggak resmi, tanpa dapat apa-apa.

    Tabel ini juga fondasi kartu Kesehatan Sumber di desain — `ingested_at`
    per sumber itu persis "kesegaran feed" yang mau ditampilin di sana.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='ingests')
    source = models.CharField(max_length=30, choices=DataSource.choices)
    ingested_at = models.DateTimeField(auto_now=True)
    # Jumlah baris yang tersimpan waktu itu — buat ngendus penarikan yang
    # "berhasil" tapi sebenernya balik kosong.
    rows = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-ingested_at']
        constraints = [
            models.UniqueConstraint(fields=['match', 'source'], name='unique_match_source_ingest')
        ]

    def __str__(self):
        return f'{self.match} <- {self.source} ({self.ingested_at:%Y-%m-%d %H:%M})'


class SourceHeartbeat(models.Model):
    """Kapan terakhir kita berhasil BICARA dengan sebuah sumber.

    Beda dari `MatchIngest`, dan bedanya penting. `MatchIngest` menjawab
    "kapan laga ini terakhir ditarik" — kalau nggak ada laga baru, dia nggak
    tersentuh sama sekali.

    Sesudah penyaring inkremental dipasang, ESPN melewati semua laga yang udah
    selesai. Hasilnya kartu Kesehatan Sumber bilang ESPN "berhenti 12 jam lalu"
    padahal dia sukses jalan tiap 10 menit — alarm palsu buat feed yang justru
    paling sehat. Ini pengulangan persis bug 4.7, cuma sebabnya beda.

    Yang dicatat di sini: "jaringannya nyambung, API-nya jawab, command-nya
    kelar tanpa error". Nggak ada data baru itu jawaban yang SAH, bukan
    kegagalan.
    """

    source = models.CharField(max_length=30, choices=DataSource.choices, unique=True)
    last_ok_at = models.DateTimeField(auto_now=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['source']

    def __str__(self):
        return f'{self.source} ok {self.last_ok_at:%Y-%m-%d %H:%M}'


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


class RawPayload(models.Model):
    """Respons mentah dari provider, disimpen sebelum diolah.

    Kenapa perlu: handoff minta laga bisa DIPUTAR ULANG tanpa narik lagi, dan
    itu prasyarat mode putar ulang di Tahap 6. Tanpa ini, satu-satunya cara
    nguji panel live adalah nunggu pertandingan berikutnya — cara paling
    lambat mengembangkan app ini.

    Gunanya yang kedua: kalau parser dibetulin, laga lama bisa diproses ulang
    dari payload aslinya. Bug tinggi badan 179510 dulu ketahuan berbulan-bulan
    setelah datanya masuk; dengan ini, perbaikannya bisa diterapkan surut.

    Cuma versi TERAKHIR per (sumber, jenis, kunci) yang disimpen — riwayat
    tiap penarikan nggak berguna buat putar ulang dan cuma bikin tabel besar.
    """

    source = models.CharField(max_length=30, choices=DataSource.choices)
    # Jenis payload, mis. 'match_details' atau 'match_shots'. Satu provider
    # bisa punya beberapa endpoint dengan bentuk berbeda.
    kind = models.CharField(max_length=40)
    # ID milik provider (match id, team id), bukan pk kita.
    key = models.CharField(max_length=80)

    payload = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)
    # Ukuran mentah buat mantau pertumbuhan tabel tanpa harus hitung ulang.
    size_bytes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-fetched_at']
        indexes = [models.Index(fields=['source', 'kind'])]
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'kind', 'key'], name='unique_raw_payload'
            )
        ]

    def __str__(self):
        return f'{self.source}/{self.kind}/{self.key}'


class FieldConflict(models.Model):
    """Dua sumber ngasih nilai berbeda buat field yang sama.

    Sebelumnya selisih begini dibuang diam-diam: resolve_updates cuma nolak
    nilai dari provider berprioritas lebih rendah tanpa nyatet bahwa mereka
    nggak sepakat. Padahal prinsip handoff jelas — konflik antar sumber nggak
    disembunyikan, tapi DITANDAI dan keputusannya diserahkan ke analis.

    Catatan: kartu Konflik Sumber di desain sebenarnya tentang status
    ketersediaan pemain, bukan nilai statistik. Itu butuh sumber cedera kedua
    yang belum ada — sekarang cuma Highlightly. Tabel ini nangani konflik yang
    memang sudah nyata datanya.
    """

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='field_conflicts')
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, null=True, blank=True, related_name='field_conflicts'
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True, related_name='field_conflicts'
    )

    field = models.CharField(max_length=60)
    # Disimpen sebagai teks karena field-nya campur int, float, dan boolean.
    kept_source = models.CharField(max_length=30, choices=DataSource.choices)
    kept_value = models.CharField(max_length=60)
    other_source = models.CharField(max_length=30, choices=DataSource.choices)
    other_value = models.CharField(max_length=60)

    detected_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [models.Index(fields=['match', 'field'])]
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'player', 'team', 'field', 'other_source'],
                name='unique_field_conflict',
            )
        ]

    def __str__(self):
        who = self.player or self.team
        return f'{who} {self.field}: {self.kept_value} ({self.kept_source}) vs {self.other_value} ({self.other_source})'


class PredictionSnapshot(models.Model):
    """Satu versi prediksi untuk satu laga, beku pada satu titik waktu.

    Ini fondasi panel Cek Prediksi — yang handoff sebut **pembeda utama
    produk**: membuktikan analisis dibuat sebelum laga, bukan setelah fakta.
    Handoff juga tegas bahwa ini tidak bisa ditambal belakangan; prediksi yang
    tidak tersimpan sebelum kick-off hilang selamanya.

    **Kenapa snapshot, bukan satu baris yang di-update.** Handoff melarang
    mekanisme kunci:

        "Tidak ada mekanisme kunci atau approval. Framing yang sudah
        disepakati dengan user: 'sampai konten ini diunggah, beginilah
        prediksi kami' — prediksi terus diperbarui otomatis sampai kick-off,
        dan tiap konten membawa cap waktu versi yang dipakai. Jangan
        menambahkan tombol lock, status 'diperiksa oleh X', atau approval
        flow; app tidak punya login sehingga klaim itu tidak bisa dibuktikan."

    Jadi tiap pembaruan bikin baris BARU, bukan menimpa yang lama. Efeknya
    sama dengan mengunci tanpa melanggar aturan itu: `prediction_before_kickoff`
    menyaring `created_at < kickoff_at`, jadi apa pun yang ditulis sesudah
    peluit tidak bisa menyamar jadi prediksi pra-laga. Yang dijamin app cuma
    apa yang benar-benar bisa dilacaknya — sesuai prinsip desain nomor 3.

    **`auto_now_add`, BUKAN `auto_now`.** Model lain di file ini pakai
    `auto_now` (MatchIngest.ingested_at, RawPayload.fetched_at,
    FieldConflict.detected_at) karena mereka memang mau tahu sentuhan
    terakhir. Di sini `auto_now` akan menulis ulang cap waktu tiap kali baris
    disimpan — prediksi yang dibuat sebelum laga mendadak bercap sesudah laga,
    dan seluruh guna tabel ini lenyap tanpa gejala. Ada test regresinya.
    """

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name='prediction_snapshots'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Catatan bebas analis: kenapa prediksinya berubah dari versi sebelumnya.
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['match', '-created_at'])]

    def __str__(self):
        return f'Prediksi {self.match} @ {self.created_at:%Y-%m-%d %H:%M}'

    @property
    def before_kickoff(self):
        """True kalau versi ini memang dibuat sebelum peluit."""
        return self.created_at < self.match.kickoff_at

    @property
    def lead_time(self):
        """Selisih waktu ke kick-off. Negatif berarti dibuat setelah laga mulai."""
        return self.match.kickoff_at - self.created_at


class HypothesisItem(models.Model):
    """Satu kartu hipotesis di panel Cek Prediksi.

    Desain minta tiga kartu per laga dengan status KENA / BELUM / MELESET
    beserta bukti angkanya.
    """

    class Outcome(models.TextChoices):
        PENDING = 'BELUM', 'Belum terjawab'
        HIT = 'KENA', 'Kena'
        MISS = 'MELESET', 'Meleset'

    snapshot = models.ForeignKey(
        PredictionSnapshot, on_delete=models.CASCADE, related_name='hypotheses'
    )
    order = models.PositiveSmallIntegerField(default=0)
    # Hipotesisnya sendiri, mis. "MU bikin peluang utama dari sisi kiri".
    text = models.CharField(max_length=300)
    # Apa yang harus dilihat untuk menjawabnya — ditulis SEBELUM laga supaya
    # kriterianya tidak digeser setelah hasilnya kelihatan.
    evidence_note = models.CharField(max_length=300, blank=True)
    outcome = models.CharField(
        max_length=8, choices=Outcome.choices, default=Outcome.PENDING
    )
    # Angka yang jadi bukti waktu dievaluasi, mis. "7 dari 11 peluang dari kiri".
    outcome_note = models.CharField(max_length=300, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['snapshot', 'order']

    def __str__(self):
        return f'[{self.outcome}] {self.text[:60]}'


class LineupSlot(models.Model):
    """Satu dari 11 posisi di prediksi susunan.

    Handoff: bulatan berlabel posisi + nama, posisi yang belum pasti diberi
    persentase keyakinan, pemain kunci ditandai. Orientasi tim menyerang ke
    kanan (bek kanan di bawah, bek kiri di atas) itu urusan render, bukan
    model — tapi `pitch_x`/`pitch_y` disediakan supaya analis bisa menggeser
    node kalau formasinya tidak standar.
    """

    class Position(models.TextChoices):
        GK = 'GK', 'Kiper'
        RB = 'RB', 'Bek kanan'
        CB = 'CB', 'Bek tengah'
        LB = 'LB', 'Bek kiri'
        DM = 'DM', 'Gelandang bertahan'
        CM = 'CM', 'Gelandang tengah'
        AM = 'AM', 'Gelandang serang'
        RW = 'RW', 'Sayap kanan'
        LW = 'LW', 'Sayap kiri'
        CF = 'CF', 'Penyerang'

    snapshot = models.ForeignKey(
        PredictionSnapshot, on_delete=models.CASCADE, related_name='lineup_slots'
    )
    slot = models.PositiveSmallIntegerField(help_text='1-11')
    # Boleh kosong: analis bisa yakin formasinya tapi belum yakin siapa yang isi.
    player = models.ForeignKey(
        Player, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='predicted_slots',
    )
    position = models.CharField(max_length=2, choices=Position.choices)
    # null = yakin. Terisi = ragu, dan UI menampilkan persentasenya.
    confidence_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    is_key = models.BooleanField(default=False)
    pitch_x = models.FloatField(null=True, blank=True)
    pitch_y = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['snapshot', 'slot']
        constraints = [
            models.UniqueConstraint(
                fields=['snapshot', 'slot'], name='unique_snapshot_slot'
            )
        ]

    def __str__(self):
        nama = self.player.name if self.player else '(belum ditentukan)'
        return f'{self.position} {nama}'
