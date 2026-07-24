import requests
from django.conf import settings


class FootballDataError(Exception):
    """Raised when football-data.org returns an error or an unexpected response."""


class FootballDataClient:
    """Thin client around football-data.org v4 API.

    Alternatif dari API-Football — free tier-nya cover musim yang sedang
    berjalan untuk Premier League & Champions League, tapi rate limit-nya
    ketat (10 request/menit) dan skema ID tim/fixture beda sama API-Football.
    """

    def __init__(self, api_key=None, base_url=None, timeout=15, session=None):
        self.api_key = api_key or settings.FOOTBALL_DATA_API_KEY
        self.base_url = (base_url or settings.FOOTBALL_DATA_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

        if not self.api_key:
            raise FootballDataError(
                'FOOTBALL_DATA_API_KEY belum di-set. Isi di file .env (lihat .env.example).'
            )

    def _headers(self):
        return {'X-Auth-Token': self.api_key}

    def _get(self, endpoint, params=None):
        url = f'{self.base_url}/{endpoint.lstrip("/")}'
        try:
            response = self.session.get(
                url, headers=self._headers(), params=params or {}, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise FootballDataError(f'Gagal request ke {url}: {exc}') from exc

        if response.status_code == 429:
            raise FootballDataError(
                'Rate limit football-data.org tercapai (10 request/menit). Coba lagi nanti.'
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise FootballDataError(f'Response tidak valid dari {url}: {exc}') from exc

        if response.status_code >= 400:
            message = payload.get('message', f'HTTP {response.status_code}')
            raise FootballDataError(f'football-data.org error untuk {url}: {message}')

        return payload

    def get_team_matches(
        self, team_id, date_from=None, date_to=None, season=None, status=None, limit=100
    ):
        params = {'limit': limit}
        if date_from is not None:
            params['dateFrom'] = date_from
        if date_to is not None:
            params['dateTo'] = date_to
        if season is not None:
            params['season'] = season
        if status is not None:
            params['status'] = status

        payload = self._get(f'teams/{team_id}/matches', params)
        return payload.get('matches', [])

    def get_team(self, team_id):
        return self._get(f'teams/{team_id}')


def get_football_data_client():
    return FootballDataClient()
