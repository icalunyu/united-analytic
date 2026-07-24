from .api_football import APIFootballClient, APIFootballError, get_api_football_client
from .espn import EspnClient, EspnError, get_espn_client
from .football_data import FootballDataClient, FootballDataError, get_football_data_client
from .highlightly import HighlightlyClient, HighlightlyError, get_highlightly_client
from .premier_league import PremierLeagueClient, PremierLeagueError, get_premier_league_client
from .thesportsdb import TheSportsDbClient, TheSportsDbError, get_thesportsdb_client

__all__ = [
    'APIFootballClient',
    'APIFootballError',
    'get_api_football_client',
    'EspnClient',
    'EspnError',
    'get_espn_client',
    'FootballDataClient',
    'FootballDataError',
    'get_football_data_client',
    'HighlightlyClient',
    'HighlightlyError',
    'get_highlightly_client',
    'PremierLeagueClient',
    'PremierLeagueError',
    'get_premier_league_client',
    'TheSportsDbClient',
    'TheSportsDbError',
    'get_thesportsdb_client',
]
