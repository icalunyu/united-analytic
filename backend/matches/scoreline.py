"""Konvensi penulisan skor: United selalu ditulis lebih dulu.

Prinsip lintas halaman dari handoff. Ditulis sekali di sini supaya tiap
halaman tidak menurunkan aturannya sendiri — itu cara "2-1" berubah arti
diam-diam antar kartu, dan pembaca tidak punya cara tahu mana yang terbalik.
"""


def sudut_pandang(match):
    """(tim_mu, tim_lawan, kandang) — kandang True kalau MU tuan rumah."""
    kandang = bool(match.home_team and match.home_team.is_manchester_united)
    if kandang:
        return match.home_team, match.away_team, True
    return match.away_team, match.home_team, False


def skor(match):
    """(gol_mu, gol_lawan) atau (None, None) kalau belum ada skor."""
    if match.home_score is None or match.away_score is None:
        return None, None
    _, _, kandang = sudut_pandang(match)
    if kandang:
        return match.home_score, match.away_score
    return match.away_score, match.home_score


def skor_teks(match, pemisah='–'):
    mu, lawan = skor(match)
    if mu is None:
        return '–'
    return f'{mu}{pemisah}{lawan}'


def hasil(match):
    """'W' / 'D' / 'L' dari sudut pandang MU, atau None."""
    mu, lawan = skor(match)
    if mu is None:
        return None
    if mu > lawan:
        return 'W'
    if mu < lawan:
        return 'L'
    return 'D'


HASIL_KATA = {'W': 'menang', 'D': 'imbang', 'L': 'kalah'}


def judul_laga(match):
    """'Manchester United 2–0 Ipswich Town' — selalu United dulu."""
    tim, lawan, _ = sudut_pandang(match)
    if tim is None or lawan is None:
        return ''
    return f'{tim.name} {skor_teks(match)} {lawan.name}'


def nama_laga(match):
    """'Manchester United vs Brighton' — tanpa skor.

    Dipakai kalimat yang skornya disebut terpisah; `judul_laga` sudah memuat
    skor, dan memakainya di kalimat yang juga menyebut skor menghasilkan
    "Manchester United 3-0 Brighton berakhir 3-0".
    """
    tim, lawan, _ = sudut_pandang(match)
    if tim is None or lawan is None:
        return ''
    return f'{tim.name} vs {lawan.name}'


def ringkas(match):
    """'MU 2–0 Ipswich (kandang)' buat chip pemilih laga."""
    _, lawan, kandang = sudut_pandang(match)
    nama = lawan.short_name or lawan.name if lawan else '?'
    return f'{skor_teks(match)} {nama}', ('kandang' if kandang else 'tandang')
