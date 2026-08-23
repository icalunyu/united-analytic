import time

import requests
from django.conf import settings

# Identitas yang jujur, BUKAN penyamaran browser.
#
# Default `python-requests/x.y` itu bukan kejujuran, cuma nilai bawaan library.
# Tapi memalsukan UA Chrome buat nembus blokir yang sengaja dipasang juga
# nggak pantas — ini API internal ESPN yang mereka nggak pernah janjiin ke
# siapa pun. Jalan tengahnya: sebut siapa kita dan di mana bisa dihubungi,
# supaya kalau ESPN mau ngeblok, mereka bisa ngeblok dengan sengaja dan tepat
# sasaran, bukan nebak-nebak.
USER_AGENT = (
    'MU-Analytics/1.0 (+https://mu-analytics.musafar.web.id; '
    'analisis internal komunitas suporter)'
)

# Error jaringan yang layak dicoba ulang: timeout dan koneksi putus. Keduanya
# kejadian nyata di log cron — "Read timed out (read timeout=15)" dan
# "ConnectionResetError(104, Connection reset by peer)", 7 kali dalam 6 hari.
#
# HTTP 4xx TIDAK termasuk: 404 nggak akan berubah jadi 200 karena diulang.
RETRYABLE_EXCEPTIONS = (requests.ConnectionError, requests.Timeout)

# 5xx itu masalah di sisi mereka dan biasanya sementara, jadi layak diulang.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class EspnError(Exception):
    """Raised when ESPN's API returns an error or an unexpected response."""


class EspnClient:
    """Thin client around ESPN's internal site API.

    Ini API yang dipakai situs/app ESPN sendiri — nggak didokumentasikan,
    nggak ada kontrak resmi buat pihak ketiga, dan bisa berubah/diblokir
    kapan aja. Dipakai di sini karena satu-satunya sumber gratis yang kasih
    match events (gol/kartu/substitusi) lengkap tanpa perlu API key.

    `league_slug` beda-beda per kompetisi (mis. 'eng.1' Premier League,
    'eng.fa' FA Cup, 'uefa.champions' Champions League) — endpoint summary
    match sendiri league-agnostic (ID event unik global), jadi cuma
    get_schedule yang butuh slug spesifik per kompetisi.
    """

    def __init__(
        self, base_url=None, league_slug=None, timeout=20, session=None, max_retries=2
    ):
        self.base_url = (base_url or settings.ESPN_BASE_URL).rstrip('/')
        self.default_league_slug = league_slug or settings.ESPN_LEAGUE_SLUG
        # Dinaikin dari 15 ke 20 detik. Kegagalan yang kecatat di log semuanya
        # "read timeout=15" — bukan koneksi ditolak, tapi ESPN yang lagi lambat
        # ngirim body. Naikin ambangnya lebih murah daripada ngulang request.
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.setdefault('User-Agent', USER_AGENT)
        # Berapa kali percobaan ulang kepakai sepanjang umur klien ini —
        # dilaporin command biar kerapuhan jaringan keukur, bukan cuma kerasa.
        self.retry_count = 0

    def _get(self, league_slug, path, params=None):
        """GET dengan percobaan ulang buat kegagalan yang sementara.

        Loop manual, bukan HTTPAdapter+Retry dari urllib3. Alasannya dua:
        polanya sama dengan `highlightly.py` yang sudah ada di repo ini, dan
        `Retry` punya perilaku yang gampang bikin kaget (`Retry.new()` bikin
        ulang objeknya lewat daftar parameter tetap, jadi atribut kustom
        kebuang diam-diam) — di jalur yang cuma jalan waktu jaringan gagal,
        yaitu justru jalur yang paling jarang kelihatan waktu tes.
        """
        url = f'{self.base_url}/{league_slug}/{path.lstrip("/")}'
        last_exc = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                self.retry_count += 1
                time.sleep(2 ** (attempt - 1))  # 1 detik, lalu 2 detik

            try:
                response = self.session.get(url, params=params or {}, timeout=self.timeout)
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                continue
            except requests.RequestException as exc:
                # Nggak layak diulang (mis. URL ngawur) — langsung nyerah.
                raise EspnError(f'Gagal request ke {url}: {exc}') from exc

            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                last_exc = EspnError(f'HTTP {response.status_code} dari {url}')
                continue

            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise EspnError(f'Gagal request ke {url}: {exc}') from exc

            try:
                return response.json()
            except ValueError as exc:
                raise EspnError(f'Response tidak valid dari {url}: {exc}') from exc

        raise EspnError(
            f'Gagal request ke {url} setelah {self.max_retries + 1} percobaan: {last_exc}'
        )

    def get_schedule(self, team_id, season=None, league_slug=None):
        params = {'season': season} if season is not None else {}
        payload = self._get(
            league_slug or self.default_league_slug, f'teams/{team_id}/schedule', params
        )
        return payload.get('events') or []

    def get_summary(self, event_id, league_slug=None):
        return self._get(league_slug or self.default_league_slug, 'summary', {'event': event_id})

    def get_scoreboard(self, date, league_slug=None):
        """Fixture by tanggal (YYYYMMDD), bukan per tim — nangkep match yang
        kadang kelewat di get_schedule (mis. friendly kecil kayak tur pramusim)."""
        payload = self._get(league_slug or self.default_league_slug, 'scoreboard', {'dates': date})
        return payload.get('events') or []


def get_espn_client():
    return EspnClient()
