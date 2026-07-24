import requests
from django.conf import settings


class APIFootballError(Exception):
    """Raised when API-Football returns an error or an unexpected response."""


class APIFootballClient:
    """Thin client around API-Football (api-sports.io / RapidAPI).

    Only wraps the endpoints needed for fixtures/match data (Fase 1).
    Callers are responsible for persisting results — this client never
    touches the database, so it stays easy to reuse from management
    commands, views, or tests.
    """

    def __init__(self, api_key=None, base_url=None, timeout=15, session=None):
        self.api_key = api_key or settings.API_FOOTBALL_KEY
        self.base_url = (base_url or settings.API_FOOTBALL_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

        if not self.api_key:
            raise APIFootballError(
                'API_FOOTBALL_KEY belum di-set. Isi di file .env (lihat .env.example).'
            )

    def _headers(self):
        if 'rapidapi.com' in self.base_url:
            return {
                'X-RapidAPI-Key': self.api_key,
                'X-RapidAPI-Host': self.base_url.replace('https://', '').replace('http://', ''),
            }
        return {'x-apisports-key': self.api_key}

    def _get(self, endpoint, params=None):
        url = f'{self.base_url}/{endpoint.lstrip("/")}'
        try:
            response = self.session.get(
                url, headers=self._headers(), params=params or {}, timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise APIFootballError(f'Gagal request ke {url}: {exc}') from exc

        payload = response.json()
        errors = payload.get('errors')
        if errors:
            raise APIFootballError(f'API-Football error untuk {url}: {errors}')

        return payload.get('response', [])

    def get_fixtures(self, team_id=None, season=None, next=None, last=None, fixture_id=None, date=None):
        """Fetch fixtures. Pass `next`/`last` for upcoming/recent N matches,
        or `fixture_id`/`date` for a specific lookup."""
        params = {}
        if team_id is not None:
            params['team'] = team_id
        if season is not None:
            params['season'] = season
        if next is not None:
            params['next'] = next
        if last is not None:
            params['last'] = last
        if fixture_id is not None:
            params['id'] = fixture_id
        if date is not None:
            params['date'] = date

        return self._get('fixtures', params)

    def get_fixture_events(self, fixture_id):
        return self._get('fixtures/events', {'fixture': fixture_id})

    def get_team(self, team_id):
        return self._get('teams', {'id': team_id})


def get_client():
    return APIFootballClient()
