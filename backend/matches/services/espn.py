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
    """

    def __init__(self, base_url=None, league_slug=None, timeout=15, session=None):
        self.base_url = (base_url or settings.ESPN_BASE_URL).rstrip('/')
        self.league_slug = league_slug or settings.ESPN_LEAGUE_SLUG
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path, params=None):
        url = f'{self.base_url}/{self.league_slug}/{path.lstrip("/")}'
        try:
            response = self.session.get(url, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EspnError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise EspnError(f'Response tidak valid dari {url}: {exc}') from exc

    def get_schedule(self, team_id, season=None):
        params = {'season': season} if season is not None else {}
        payload = self._get(f'teams/{team_id}/schedule', params)
        return payload.get('events') or []

    def get_summary(self, event_id):
        return self._get('summary', {'event': event_id})


def get_espn_client():
    return EspnClient()
