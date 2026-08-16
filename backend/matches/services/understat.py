import requests
from django.conf import settings


class UnderstatError(Exception):
    """Raised when Understat returns an error or an unexpected response."""


class UnderstatClient:
    """Client buat endpoint JSON internal understat.com.

    Understat dulu nempelin datanya sebagai variabel JS di dalam HTML
    (`datesData = JSON.parse(...)`) — pola yang dipakai hampir semua tutorial
    scraping di internet. Sekarang HTML-nya udah kosong dan datanya pindah ke
    endpoint JSON tersendiri.

    Satu-satunya syarat akses: header `X-Requested-With: XMLHttpRequest`.
    Tanpa itu server balas 404 (bukan 403) — jadi kalau suatu hari command
    ini mendadak 404 semua, kemungkinan besar syarat headernya yang berubah,
    bukan match-nya yang nggak ada.

    Cakupan: 6 liga top Eropa sejak musim 2014/15. Buat MU artinya cuma
    Premier League — kompetisi cup nggak ada di sini.
    """

    def __init__(self, base_url=None, timeout=20, session=None):
        self.base_url = (base_url or settings.UNDERSTAT_BASE_URL).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path):
        url = f'{self.base_url}/{path.lstrip("/")}'
        try:
            response = self.session.get(
                url,
                headers={'X-Requested-With': 'XMLHttpRequest'},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UnderstatError(f'Gagal request ke {url}: {exc}') from exc

        try:
            return response.json()
        except ValueError as exc:
            raise UnderstatError(f'Response tidak valid dari {url}: {exc}') from exc

    def get_team_matches(self, team_name=None, season=None):
        """Daftar match 1 tim dalam 1 musim, lengkap sama xG kedua tim.

        Return list of dict: id, isResult, side, h, a, goals, xG, datetime.
        """
        team = team_name or settings.UNDERSTAT_MU_TEAM_NAME
        season = season or settings.UNDERSTAT_DEFAULT_SEASON
        payload = self._get(f'getTeamData/{requests.utils.quote(team)}/{season}')
        return payload.get('dates') or []

    def get_match(self, match_id):
        """Detail 1 match: `shots` (per tembakan, ada xG) dan `rosters`
        (per pemain, ada xG/xA/xGChain/xGBuildup/menit main)."""
        return self._get(f'getMatchData/{match_id}')


def get_understat_client():
    return UnderstatClient()
