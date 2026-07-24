import requests
from django.conf import settings


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

    def __init__(self, base_url=None, league_slug=None, timeout=15, session=None):
        self.base_url = (base_url or settings.ESPN_BASE_URL).rstrip('/')
        self.default_league_slug = league_slug or settings.ESPN_LEAGUE_SLUG
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, league_slug, path, params=None):
        url = f'{self.base_url}/{league_slug}/{path.lstrip("/")}'
        try:
            response = self.session.get(url, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EspnError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise EspnError(f'Response tidak valid dari {url}: {exc}') from exc

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
