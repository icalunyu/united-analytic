import requests
from django.conf import settings


class TheSportsDbError(Exception):
    """Raised when TheSportsDB returns an error or an unexpected response."""


class TheSportsDbClient:
    """Thin client around TheSportsDB v1 API.

    Nggak butuh signup — pakai public test key (default '123'). Dipakai
    sebagai fallback fixtures & squad kalau provider lain (API-Football,
    football-data.org) kena quota. Banyak tim/pemain di sini udah include
    `idAPIfootball`, jadi bisa di-link langsung ke data API-Football kita
    tanpa perlu cocokin nama.
    """

    def __init__(self, api_key=None, base_url=None, timeout=15, session=None):
        self.api_key = api_key or settings.THESPORTSDB_API_KEY
        self.base_url = (base_url or settings.THESPORTSDB_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, endpoint, params=None):
        url = f'{self.base_url}/{self.api_key}/{endpoint.lstrip("/")}'
        try:
            response = self.session.get(url, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TheSportsDbError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise TheSportsDbError(f'Response tidak valid dari {url}: {exc}') from exc

    def search_team(self, name):
        payload = self._get('searchteams.php', {'t': name})
        return payload.get('teams') or []

    def get_team(self, team_id):
        payload = self._get('lookupteam.php', {'id': team_id})
        teams = payload.get('teams') or []
        return teams[0] if teams else None

    def get_next_events(self, team_id):
        payload = self._get('eventsnext.php', {'id': team_id})
        return payload.get('events') or []

    def get_last_events(self, team_id):
        payload = self._get('eventslast.php', {'id': team_id})
        return payload.get('results') or []

    def get_roster(self, team_id):
        payload = self._get('lookup_all_players.php', {'id': team_id})
        return payload.get('player') or []


def get_thesportsdb_client():
    return TheSportsDbClient()
