import requests
from django.conf import settings


class PremierLeagueError(Exception):
    """Raised when the Premier League (PulseLive) API returns an error."""


class PremierLeagueClient:
    """Thin client around footballapi.pulselive.com — backend data resmi
    premierleague.com sendiri (didukung Opta).

    Nggak ada developer portal/ToS eksplisit buat pihak ketiga, tapi ini
    first-party data, bukan hasil scraping situs lain. Riwayat lengkap sejak
    musim 1992/93, cuma cover kompetisi Premier League.
    """

    def __init__(self, base_url=None, origin=None, timeout=15, session=None):
        self.base_url = (base_url or settings.PL_BASE_URL).rstrip('/')
        self.origin = origin or settings.PL_ORIGIN_HEADER
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path, params=None):
        url = f'{self.base_url}/{path.lstrip("/")}'
        try:
            response = self.session.get(
                url, params=params or {}, headers={'Origin': self.origin}, timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PremierLeagueError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise PremierLeagueError(f'Response tidak valid dari {url}: {exc}') from exc

    def get_fixtures(self, team_id, comp_id=1, page=0, page_size=100, sort='desc'):
        payload = self._get(
            'fixtures',
            {
                'teams': team_id,
                'comps': comp_id,
                'page': page,
                'pageSize': page_size,
                'sort': sort,
            },
        )
        return payload.get('content') or []

    def get_fixture_detail(self, fixture_id):
        return self._get(f'fixtures/{fixture_id}')

    def get_player(self, person_id):
        return self._get(f'players/{person_id}')


def get_premier_league_client():
    return PremierLeagueClient()
