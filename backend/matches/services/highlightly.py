import time

import requests
from django.conf import settings


class HighlightlyError(Exception):
    """Raised when Highlightly returns an error or an unexpected response."""


class HighlightlyClient:
    """Thin client around Highlightly Football API.

    Satu provider buat squad, injuries (di dalam player summary), dan match
    events — beda dari API-Football/football-data.org yang harus dipisah
    per jenis data. x-rapidapi-host cuma perlu diisi kalau akses lewat
    marketplace RapidAPI, bukan langsung di highlightly.net.
    """

    def __init__(
        self, api_key=None, base_url=None, api_host=None, timeout=15, session=None, max_retries=3
    ):
        self.api_key = api_key or settings.HIGHLIGHTLY_API_KEY
        self.base_url = (base_url or settings.HIGHLIGHTLY_BASE_URL).rstrip('/')
        self.api_host = api_host if api_host is not None else settings.HIGHLIGHTLY_API_HOST
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_retries = max_retries

        if not self.api_key:
            raise HighlightlyError(
                'HIGHLIGHTLY_API_KEY belum di-set. Isi di file .env (lihat .env.example).'
            )

    def _headers(self):
        headers = {'x-rapidapi-key': self.api_key}
        if self.api_host:
            headers['x-rapidapi-host'] = self.api_host
        return headers

    def _get(self, endpoint, params=None):
        url = f'{self.base_url}/{endpoint.lstrip("/")}'

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, headers=self._headers(), params=params or {}, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise HighlightlyError(f'Gagal request ke {url}: {exc}') from exc

            if response.status_code == 429:
                try:
                    message = response.json().get('message', '')
                except ValueError:
                    message = ''

                if 'daily' in message.lower():
                    # Quota harian abis — retry nggak akan ngebantu sampai reset.
                    raise HighlightlyError(
                        f'Quota harian Highlightly abis: {message or "daily limit reached"}'
                    )

                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s
                    continue
                raise HighlightlyError(
                    'Rate limit Highlightly tercapai terus setelah beberapa kali coba. '
                    'Coba lagi nanti.'
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise HighlightlyError(f'Response tidak valid dari {url}: {exc}') from exc

            if response.status_code >= 400:
                message = payload.get('message', f'HTTP {response.status_code}')
                raise HighlightlyError(f'Highlightly error untuk {url}: {message}')

            return payload

    def search_teams(self, name, limit=10):
        payload = self._get('teams', {'name': name, 'limit': limit})
        return payload.get('data', payload if isinstance(payload, list) else [])

    def get_team(self, team_id):
        return self._get(f'teams/{team_id}')

    def get_matches(self, team_id=None, season=None, date=None, limit=100, offset=0):
        params = {'limit': limit, 'offset': offset}
        if team_id is not None:
            params['homeTeamId'] = team_id
        if season is not None:
            params['season'] = season
        if date is not None:
            params['date'] = date

        payload = self._get('matches', params)
        matches = payload.get('data', payload if isinstance(payload, list) else [])

        if team_id is not None:
            # homeTeamId doang nggak nangkep away matches, jadi query 2x dan gabungin.
            away_params = dict(params)
            away_params.pop('homeTeamId')
            away_params['awayTeamId'] = team_id
            away_payload = self._get('matches', away_params)
            away_matches = away_payload.get('data', away_payload if isinstance(away_payload, list) else [])
            existing_ids = {m.get('id') for m in matches}
            matches += [m for m in away_matches if m.get('id') not in existing_ids]

        return matches

    def get_match_events(self, match_id):
        return self._get(f'events/{match_id}')

    def get_player(self, player_id):
        return self._get(f'players/{player_id}')


def get_highlightly_client():
    return HighlightlyClient()
