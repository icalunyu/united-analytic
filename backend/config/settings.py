"""
Django settings for config project.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-only-change-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DJANGO_DEBUG', True)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'matches',
    'players',
    'transfers',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# Dev default: SQLite. Production (cPanel): Postgres via env vars.
if os.environ.get('DB_ENGINE') == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', ''),
            'USER': os.environ.get('DB_USER', ''),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Host ini nggak punya web server config terpisah buat static files —
# Django (lewat whitenoise) yang serve semuanya sendiri, dev maupun prod.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}


# CORS (frontend React dev server / static build origin)

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:5173').split(',')
    if origin.strip()
]


# API-Football (api-sports.io / RapidAPI)

API_FOOTBALL_BASE_URL = os.environ.get('API_FOOTBALL_BASE_URL', 'https://v3.football.api-sports.io')
API_FOOTBALL_KEY = os.environ.get('API_FOOTBALL_KEY', '')
# Manchester United's team ID in API-Football is 33 by default; override via env if needed.
MU_TEAM_ID = int(os.environ.get('MU_TEAM_ID', '33'))


# football-data.org (sumber alternatif — free tier cover musim berjalan utk
# Premier League & Champions League, beda skema ID tim dari API-Football)

FOOTBALL_DATA_BASE_URL = os.environ.get('FOOTBALL_DATA_BASE_URL', 'https://api.football-data.org/v4')
FOOTBALL_DATA_API_KEY = os.environ.get('FOOTBALL_DATA_API_KEY', '')
# Manchester United's team ID in football-data.org is 66 by default; override via env if needed.
FOOTBALL_DATA_MU_TEAM_ID = int(os.environ.get('FOOTBALL_DATA_MU_TEAM_ID', '66'))


# Highlightly (via RapidAPI atau langsung) — punya squad, injuries, & match
# events dalam 1 provider. HIGHLIGHTLY_API_HOST cuma perlu diisi kalau daftar
# lewat marketplace RapidAPI, bukan langsung di highlightly.net.

HIGHLIGHTLY_BASE_URL = os.environ.get('HIGHLIGHTLY_BASE_URL', 'https://soccer.highlightly.net')
HIGHLIGHTLY_API_KEY = os.environ.get('HIGHLIGHTLY_API_KEY', '')
HIGHLIGHTLY_API_HOST = os.environ.get('HIGHLIGHTLY_API_HOST', '')
# Team ID Manchester United di Highlightly (ketemu lewat /teams?name=Manchester United).
HIGHLIGHTLY_MU_TEAM_ID = os.environ.get('HIGHLIGHTLY_MU_TEAM_ID', '28867')


# TheSportsDB — nggak butuh signup, pakai public test key. Rate limit lebih
# longgar (30 req/menit) dan tim/pemainnya udah include idAPIfootball buat
# cross-reference langsung ke API-Football (bukan cuma cocokin nama).
# Dipakai sebagai fallback fixtures & squad kalau provider lain kena quota.

THESPORTSDB_BASE_URL = os.environ.get('THESPORTSDB_BASE_URL', 'https://www.thesportsdb.com/api/v1/json')
THESPORTSDB_API_KEY = os.environ.get('THESPORTSDB_API_KEY', '123')
THESPORTSDB_MU_TEAM_ID = os.environ.get('THESPORTSDB_MU_TEAM_ID', '133612')


# ESPN — API internal situs/app ESPN sendiri, bukan produk resmi buat pihak
# ketiga (nggak didokumentasikan, bisa berubah/diblokir kapan aja tanpa
# pemberitahuan). Nggak butuh key. Sumber match events (gol/kartu/substitusi)
# paling lengkap yang kita punya sejauh ini.

ESPN_BASE_URL = os.environ.get('ESPN_BASE_URL', 'https://site.api.espn.com/apis/site/v2/sports/soccer')
ESPN_LEAGUE_SLUG = os.environ.get('ESPN_LEAGUE_SLUG', 'eng.1')
ESPN_MU_TEAM_ID = os.environ.get('ESPN_MU_TEAM_ID', '360')
# Semua kompetisi yang mungkin diikutin MU — endpoint schedule ESPN di-scope
# per kompetisi, jadi perlu di-loop satu-satu (summary match-nya sendiri
# league-agnostic, nggak perlu di-loop).
ESPN_COMPETITION_SLUGS = os.environ.get(
    'ESPN_COMPETITION_SLUGS',
    'eng.1,eng.fa,eng.league_cup,uefa.champions,uefa.europa,uefa.europa.conf,eng.charity,club.friendly',
)


# Premier League (PulseLive/Opta) — backend data resmi premierleague.com
# sendiri. Nggak ada developer portal/ToS eksplisit buat pihak ketiga, tapi
# ini first-party data (bukan scraping situs lain). Riwayat lengkap sejak
# musim 1992/93, cuma cover kompetisi Premier League doang.

# FotMob — API internal situs/app mereka, statusnya sama kayak ESPN (nggak
# resmi buat pihak ketiga, bisa berubah kapan aja). Nggak butuh key, tapi
# nolak request tanpa header Referer.
#
# Ini satu-satunya sumber gratis yang ngasih aksi bertahan PER PEMAIN
# (tackles/interceptions/recoveries) dan umpan yang dipisah paruh sendiri vs
# paruh lawan — dua bahan yang bikin PPDA bisa dihitung.

FOTMOB_BASE_URL = os.environ.get('FOTMOB_BASE_URL', 'https://www.fotmob.com')
FOTMOB_MU_TEAM_ID = os.environ.get('FOTMOB_MU_TEAM_ID', '10260')
# ID Premier League di FotMob. Dipakai buat narik seluruh fixture liga dalam
# satu panggilan — bahan tolok ukur se-liga (persentil posisi, peringkat).
FOTMOB_PL_LEAGUE_ID = os.environ.get('FOTMOB_PL_LEAGUE_ID', '47')


# Understat — satu-satunya sumber xG gratis yang cover Premier League.
# Nggak butuh API key, tapi endpoint JSON-nya cuma jalan kalau request bawa
# header X-Requested-With (lihat services/understat.py). Cakupannya cuma 6
# liga top Eropa — buat MU berarti Premier League doang, nggak ada cup.

UNDERSTAT_BASE_URL = os.environ.get('UNDERSTAT_BASE_URL', 'https://understat.com')
# Nama tim di Understat dipakai langsung di URL, bukan ID numerik.
UNDERSTAT_MU_TEAM_NAME = os.environ.get('UNDERSTAT_MU_TEAM_NAME', 'Manchester United')
def _current_football_season(today=None):
    """Tahun musim berjalan menurut penomoran Understat (musim 2026 = 2026/27).

    Musim Eropa mulai Agustus. Sebelum Juli, kita masih di musim yang dibuka
    tahun sebelumnya. Dulu nilainya dipatok '2025' dan diam-diam basi begitu
    musim baru mulai: seluruh 38 laga musim lama sudah tertarik, jadi
    pull_xg_understat lapor "0 laga dicocokkan" tiap malam tanpa error, dan
    laga musim berjalan nggak pernah dapat xG sama sekali.
    """
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


UNDERSTAT_DEFAULT_SEASON = os.environ.get(
    'UNDERSTAT_DEFAULT_SEASON'
) or str(_current_football_season())


PL_BASE_URL = os.environ.get('PL_BASE_URL', 'https://footballapi.pulselive.com/football')
PL_ORIGIN_HEADER = os.environ.get('PL_ORIGIN_HEADER', 'https://www.premierleague.com')
PL_MU_TEAM_ID = os.environ.get('PL_MU_TEAM_ID', '12')
PL_COMPETITION_ID = os.environ.get('PL_COMPETITION_ID', '1')
