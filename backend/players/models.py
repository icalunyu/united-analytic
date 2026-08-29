from django.db import models


class DataSource(models.TextChoices):
    """Sumber data eksternal yang bisa nge-supply Team/Match. Nambah provider
    baru cukup nambah 1 value di sini — nggak perlu migration schema baru."""

    API_FOOTBALL = 'api_football', 'API-Football'
    FOOTBALL_DATA = 'football_data', 'football-data.org'
    HIGHLIGHTLY = 'highlightly', 'Highlightly'
    THESPORTSDB = 'thesportsdb', 'TheSportsDB'
    ESPN = 'espn', 'ESPN'
    ESPN_COMMENTARY = 'espn_commentary', 'ESPN (parsed dari commentary teks)'
    PREMIER_LEAGUE = 'premier_league', 'Premier League (PulseLive)'
    UNDERSTAT = 'understat', 'Understat (xG)'
    FOTMOB = 'fotmob', 'FotMob'
    FPL = 'fpl', 'Fantasy Premier League'
    NEWS = 'news', 'Umpan berita'


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


class PlayerAvailability(models.Model):
    """Status ketersediaan pemain MENURUT SATU SUMBER.

    Kenapa per-sumber, bukan satu status gabungan: panel Konflik Sumber di
    desain justru minta **dua kotak berdampingan** — sumber A bilang apa,
    sumber D bilang apa, masing-masing dengan umur datanya. Kalau kita gabung
    duluan jadi satu nilai, konfliknya hilang sebelum sempat ditampilkan, dan
    analis nggak punya bahan buat memutuskan.

    Beda dari `Injury`, dan bedanya penting. `Injury` itu RIWAYAT — satu baris
    per kejadian cedera, punya tanggal mulai dan selesai. Ini KEADAAN SEKARANG,
    satu baris per (pemain, sumber), ditimpa tiap penarikan.

    Pelajaran yang mahal: Highlightly selama ini dipakai sebagai sumber status
    dan hasilnya 263 dari 264 entri MU berstatus RETURNED. Sesudah diperiksa,
    Highlightly ternyata feed RIWAYAT KARIER — entri terbaru Mason Mount
    berakhir September 2021. Yang salah bukan kodenya, tapi harapan kita
    terhadap sumbernya.
    """

    class Status(models.TextChoices):
        FIT = 'FIT', 'Bugar'
        DOUBTFUL = 'DOUBT', 'Diragukan'
        OUT = 'OUT', 'Absen'
        SUSPENDED = 'SUSP', 'Skorsing'
        LOANED = 'LOAN', 'Dipinjamkan'
        UNKNOWN = 'UNK', 'Tidak dicakup sumber'

    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name='availability'
    )
    source = models.CharField(max_length=30, choices=DataSource.choices)
    status = models.CharField(max_length=6, choices=Status.choices)
    # Teks apa adanya dari sumbernya, mis. 'Foot injury - 75% chance of playing'.
    note = models.CharField(max_length=255, blank=True)
    # Derajat keraguan kalau sumbernya ngasih (FPL: 0/25/50/75/100).
    chance_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    expected_return = models.DateField(null=True, blank=True)
    # Kapan SUMBERNYA memperbarui info ini — bukan kapan kita menariknya.
    # Ini yang dipakai kolom "umur data" di panel Konflik Sumber; tanpa ini
    # kita cuma tahu kapan cron jalan, bukan kapan kabarnya berubah.
    source_updated_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['player__name', 'source']
        verbose_name_plural = 'player availability'
        constraints = [
            models.UniqueConstraint(
                fields=['player', 'source'], name='unique_player_source_availability'
            )
        ]

    def __str__(self):
        return f'{self.player.name}: {self.get_status_display()} ({self.source})'

    @property
    def bermasalah(self):
        """True kalau status ini bukan 'bugar' — dipakai buat menyaring UI."""
        return self.status not in (self.Status.FIT, self.Status.UNKNOWN)


class AvailabilityDecision(models.Model):
    """Pilihan ANALIS waktu dua sumber berselisih soal status seorang pemain.

    Ini butir yang di checklist tertulis "Pilihan analis tersimpan — tidak ada
    tempat menyimpannya". Sekarang ada tempatnya.

    Kenapa statusnya ikut disalin, bukan cuma sumbernya: sumber bisa berubah
    pikiran besok pagi. Kalau kita cuma menyimpan "analis memilih FPL", lalu
    FPL diam-diam mengubah Amad dari 75% jadi absen, keputusan yang tercatat
    berubah artinya tanpa ada yang menyentuhnya. Menyalin statusnya bikin
    keputusan itu tetap berarti apa yang dimaksud waktu diambil — dan bikin
    kita bisa memberi tahu analis kalau sumbernya sudah bergeser sejak itu.

    Aturan SQ-01 yang tidak dilanggar model ini: pilihan analis **bukan data
    sumber**. Dia disimpan di tabel terpisah, tidak pernah ditulis balik ke
    `PlayerAvailability`, jadi penarikan berikutnya tidak bisa menimpanya dan
    angka sumber tidak pernah tercemar tangan manusia.
    """

    player = models.OneToOneField(
        Player, on_delete=models.CASCADE, related_name='availability_decision'
    )
    # Sumber yang dimenangkan analis.
    source = models.CharField(max_length=30, choices=DataSource.choices)
    # Status milik sumber itu PADA SAAT diputuskan.
    status = models.CharField(max_length=6, choices=PlayerAvailability.Status.choices)
    note = models.CharField(max_length=255, blank=True)
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['player__name']

    def __str__(self):
        return f'{self.player.name}: pilih {self.source} ({self.status})'
