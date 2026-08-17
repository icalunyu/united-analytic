import requests
from django.conf import settings


class FotMobError(Exception):
    """Raised when FotMob returns an error or an unexpected response."""


class FotMobClient:
    """Client buat API internal fotmob.com.

    Status sama kayak ESPN: API yang dipakai situs/app mereka sendiri, bukan
    produk resmi buat pihak ketiga. Nggak butuh key, tapi endpoint-nya nolak
    request tanpa header `Referer` — dan path-nya pernah pindah dari
    `/api/...` ke `/api/data/...`, jadi kalau tiba-tiba 404 semua, itu
    tersangka pertamanya.

    Nilainya buat kita: ini satu-satunya sumber gratis yang ngasih statistik
    aksi bertahan per pemain (tackles, interceptions, recoveries) dan umpan
    yang dipisah paruh sendiri/paruh lawan — dua bahan yang bikin PPDA bisa
    dihitung. ESPN nggak punya dua-duanya.
    """

    BROWSER_UA = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    )

    def __init__(self, base_url=None, timeout=25, session=None):
        self.base_url = (base_url or settings.FOTMOB_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path, params=None):
        url = f'{self.base_url}/{path.lstrip("/")}'
        try:
            response = self.session.get(
                url,
                params=params or {},
                headers={'User-Agent': self.BROWSER_UA, 'Referer': f'{self.base_url}/'},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FotMobError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise FotMobError(f'Response tidak valid dari {url}: {exc}') from exc

    def get_team_fixtures(self, team_id=None):
        """Daftar fixture 1 tim (lewat + akan datang) berikut match id FotMob."""
        team_id = team_id or settings.FOTMOB_MU_TEAM_ID
        payload = self._get('api/data/teams', {'id': team_id})
        overview = payload.get('overview') or {}
        return overview.get('overviewFixtures') or []

    def get_match(self, match_id):
        """Detail 1 laga: playerStats, stats tim per babak, shotmap, momentum."""
        return self._get('api/data/matchDetails', {'matchId': match_id})


def get_fotmob_client():
    return FotMobClient()
