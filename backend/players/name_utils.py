import re
import unicodedata

_SUFFIX_PATTERN = re.compile(r'\b(FC|CF|AFC|SC|CD|AC)\b\.?', re.IGNORECASE)
_NON_ALNUM_PATTERN = re.compile(r'[^a-z0-9\s]')
_WHITESPACE_PATTERN = re.compile(r'\s+')

# Huruf yang NFKD nggak bisa pecah jadi "huruf dasar + tanda". Buat karakter
# kayak gini nggak ada aksen yang bisa dicopot — hurufnya sendiri yang beda,
# jadi harus dipetakan manual. 'ı' (dotless i, Turki) contoh yang paling sering
# kena di nama pemain: 'Bayındır' vs 'Bayindir'.
_MANUAL_FOLD = str.maketrans(
    {
        'ı': 'i',
        'ø': 'o',
        'đ': 'd',
        'ð': 'd',
        'ł': 'l',
        'þ': 'th',
        'ß': 'ss',
        'æ': 'ae',
        'œ': 'oe',
    }
)


def fold_accents(text):
    """Turunin huruf beraksen ke huruf dasarnya: 'Šeško' -> 'sesko'.

    Provider beda beda cara nulis nama yang sama — Highlightly pakai ejaan
    beraksen, yang lain nggak — jadi tanpa ini 'Benjamin Šeško' dan
    'Benjamin Sesko' ke-anggep dua orang beda dan bikin row duplikat.

    NFKD mecah huruf beraksen jadi huruf dasar + tanda diakritik terpisah,
    lalu tandanya dibuang. Yang nggak bisa dipecah NFKD ditangani lewat
    _MANUAL_FOLD.
    """
    text = (text or '').lower().translate(_MANUAL_FOLD)
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def normalize_team_name(name):
    """Samain nama tim antar provider: buang suffix klub (FC/AFC/dll), aksen,
    tanda baca, dan spasi berlebih."""
    name = _SUFFIX_PATTERN.sub('', name or '')
    # Harus sebelum _NON_ALNUM_PATTERN: pola itu ganti tiap karakter non-ASCII
    # jadi SPASI, jadi tanpa fold duluan 'Beşiktaş' kepecah jadi 'be ikta'
    # dan nama tim malah hancur, bukan cuma beda ejaan.
    name = fold_accents(name)
    name = _NON_ALNUM_PATTERN.sub(' ', name)
    name = _WHITESPACE_PATTERN.sub(' ', name).strip()
    return name


def team_names_match(name_a, name_b):
    """True kalau 2 nama kemungkinan besar tim yang sama.

    Provider beda suka pakai nama pendek vs nama resmi lengkap — misal
    API-Football nyimpen 'Brighton' sementara football-data.org nyimpen
    'Brighton & Hove Albion FC'. Exact match aja nggak cukup, jadi kita cek
    juga apakah kata-kata di nama yang lebih pendek adalah prefix persis
    dari nama yang lebih panjang (bukan cuma kata pertama — biar 'Manchester
    United' tetep ke-anggep beda dari 'Manchester City').
    """
    norm_a = normalize_team_name(name_a)
    norm_b = normalize_team_name(name_b)
    if norm_a == norm_b:
        return True

    words_a = norm_a.split()
    words_b = norm_b.split()
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    if not shorter:
        return False

    return longer[: len(shorter)] == shorter


def player_identity_key(name):
    """Ambil (inisial depan, nama belakang) sebagai kunci matching. Provider
    suka beda format display name — 'S. Amrabat' (API-Football) vs 'Sofyan
    Amrabat' (football-data.org) vs 'L. Shaw' (Highlightly event) vs 'Luke
    Shaw' (football-data.org squad) — tapi inisial+nama belakang biasanya
    konsisten."""
    name = fold_accents(name).replace('.', ' ')
    words = [w for w in _WHITESPACE_PATTERN.sub(' ', name).strip().split() if w]
    if not words:
        return '', ''
    surname = words[-1]
    initial = words[0][0] if len(words) > 1 else ''
    return initial, surname


def player_names_match(name_a, name_b):
    """Cocokin nama belakang + inisial depan (kalau ada di 2-2nya). Nama
    belakang doang ketauan nggak cukup — 2 pemain akademi beda orang bisa
    kebetulan sama-sama 'Fletcher'. Inisial nyaring kasus itu ('T. Fletcher'
    vs 'J. Fletcher' jelas beda), tapi kalau salah satu namanya cuma 1 kata
    (mononym, nggak ada inisial buat dibandingin) tetep fallback ke nama
    belakang doang — masih ada risiko residual buat kasus itu."""
    initial_a, surname_a = player_identity_key(name_a)
    initial_b, surname_b = player_identity_key(name_b)

    if not surname_a or surname_a != surname_b:
        return False
    if initial_a and initial_b:
        return initial_a == initial_b
    return True
