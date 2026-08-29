"""Rekonsiliasi status ketersediaan pemain — SQ-01 & SQ-02.

Fungsi murni + satu fungsi yang menyentuh DB, pola yang sama seperti
`matches/workload.py`.

**Aturan SQ-01, apa adanya dari inventaris kartu:**

1. Dua sumber beda status untuk pemain yang sama = konflik.
2. Selama belum diputuskan, status pemain itu di tabel ditulis `Bentrok` dan
   diberi tanda jangan dipakai untuk konten.
3. Pilihan analis menimpa keduanya dan dicatat sebagai pilihan manual, bukan
   data sumber.
4. Susunan resmi yang terbit satu jam sebelum kick-off menimpa semuanya.

**Satu penyimpangan yang disengaja dari urutan prioritas di handoff.** Handoff
menulis urutannya "pengumuman resmi klub, lalu sumber tingkat A, lalu
agregator". Kita tidak punya API pengumuman resmi klub — yang kita punya
adalah judul berita yang dibaca kata kuncinya. Menaruh turunan-kata-kunci di
puncak prioritas berarti sebuah judul yang salah baca bisa mengalahkan feed
terstruktur, dan itu kebalikan dari maksud aturannya. Jadi FPL (data resmi
Premier League, terstruktur) ditaruh di atas NEWS (turunan judul).

Kalau suatu hari ada umpan resmi manutd.com yang terstruktur, dia masuk di
atas FPL dan komentar ini yang harus diubah, bukan diam-diam ditukar.
"""

from datetime import timedelta

from players.models import DataSource, PlayerAvailability

Status = PlayerAvailability.Status

# Makin awal = makin dipercaya. Lihat catatan penyimpangan di docstring.
PRIORITAS = (
    DataSource.FPL,
    DataSource.NEWS,
    DataSource.HIGHLIGHTLY,
    DataSource.FOTMOB,
)

# Status yang artinya "sumber ini tidak punya klaim". Sengaja dikeluarkan dari
# perbandingan: kalau FPL bilang 'absen' dan sumber lain bilang 'tidak dicakup',
# itu bukan konflik — cuma satu sumber yang tahu.
TANPA_KLAIM = (Status.UNKNOWN,)

# Warna pill di tabel SQ-02. Diambil dari varian kartu:
# fit hijau, ragu kuning, cedera merah, bentrok ungu.
PILL = {
    Status.FIT: ('Bugar', 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'),
    Status.DOUBTFUL: ('Diragukan', 'bg-amber-400/15 text-amber-300 ring-amber-400/30'),
    Status.OUT: ('Absen', 'bg-red-500/15 text-red-300 ring-red-500/30'),
    Status.SUSPENDED: ('Skorsing', 'bg-red-500/15 text-red-300 ring-red-500/30'),
    Status.LOANED: ('Dipinjamkan', 'bg-sky-500/15 text-sky-300 ring-sky-500/30'),
    Status.UNKNOWN: ('Tak diketahui', 'bg-white/5 text-gray-400 ring-white/10'),
}
PILL_BENTROK = ('Bentrok', 'bg-purple-500/15 text-purple-300 ring-purple-500/30')


def label_sumber(kode):
    return dict(DataSource.choices).get(kode, kode)


def umur_teks(waktu, sekarang):
    """'3 jam lalu' — umur data, kolom yang diminta eksplisit di SQ-01.

    Return None kalau sumbernya tidak memberi tahu kapan kabarnya berubah.
    Itu ditampilkan sebagai 'umur tidak diketahui', bukan sebagai 'baru',
    karena keduanya jauh berbeda artinya buat analis.
    """
    if waktu is None:
        return None
    detik = (sekarang - waktu).total_seconds()
    if detik < 0:
        return 'baru saja'
    menit = int(detik // 60)
    if menit < 60:
        return f'{menit} menit lalu' if menit else 'baru saja'
    jam = menit // 60
    if jam < 48:
        return f'{jam} jam lalu'
    return f'{jam // 24} hari lalu'


def berklaim(entri):
    """Entri yang benar-benar mengklaim sesuatu, urut prioritas."""
    punya = [e for e in entri if e.status not in TANPA_KLAIM]
    urut = {s: i for i, s in enumerate(PRIORITAS)}
    return sorted(punya, key=lambda e: urut.get(e.source, len(PRIORITAS)))


def berselisih(entri):
    """True kalau ada dua sumber berklaim dengan status berbeda."""
    return len({e.status for e in berklaim(entri)}) > 1


def putuskan(entri, keputusan=None, lewat_susunan_resmi=False):
    """Status akhir satu pemain + dari mana asalnya.

    Return dict: status, asal, sumber, catatan.
    `asal` salah satu dari: 'susunan', 'analis', 'bentrok', 'sumber', 'kosong'.
    Nilainya menentukan apa yang boleh dipakai untuk konten — cuma 'bentrok'
    yang tidak boleh.
    """
    # Aturan 4 menang atas segalanya, termasuk atas pilihan analis. Susunan
    # resmi bukan pendapat; pemain yang namanya ada di situ jelas bisa main.
    if lewat_susunan_resmi:
        return {
            'status': Status.FIT,
            'asal': 'susunan',
            'sumber': None,
            'catatan': 'Namanya ada di susunan resmi yang sudah terbit',
        }

    klaim = berklaim(entri)
    if not klaim:
        return {'status': Status.UNKNOWN, 'asal': 'kosong', 'sumber': None, 'catatan': ''}

    if keputusan is not None:
        dipilih = next((e for e in klaim if e.source == keputusan.source), None)
        catatan = keputusan.note
        # Sumbernya boleh berubah pikiran sesudah analis memutuskan. Kalau itu
        # terjadi, keputusannya tetap dipakai TAPI perbedaannya disebut — diam
        # soal ini bikin analis mengira dia masih melihat data terbaru.
        if dipilih is not None and dipilih.status != keputusan.status:
            catatan = (
                f'{catatan} · {label_sumber(keputusan.source)} sudah berubah jadi '
                f'"{dipilih.get_status_display()}" sesudah keputusan ini diambil'
            ).strip(' ·')
        return {
            'status': keputusan.status,
            'asal': 'analis',
            'sumber': keputusan.source,
            'catatan': catatan,
        }

    if len({e.status for e in klaim}) > 1:
        return {
            'status': None,
            'asal': 'bentrok',
            'sumber': None,
            'catatan': 'Sumber berselisih dan belum diputuskan',
        }

    utama = klaim[0]
    return {
        'status': utama.status,
        'asal': 'sumber',
        'sumber': utama.source,
        'catatan': utama.note,
    }


def pill(hasil):
    """(label, kelas css) buat kolom Status di SQ-02."""
    if hasil['asal'] == 'bentrok':
        return PILL_BENTROK
    return PILL.get(hasil['status'], PILL[Status.UNKNOWN])


# ------------------------------------------------------------------ DB

# Susunan resmi biasanya terbit satu jam sebelum kick-off. Kita menerima
# jendela lebih lebar ke depan karena penarikan kita tidak tepat waktu.
JENDELA_SUSUNAN = timedelta(hours=2)


def susunan_resmi(team, sekarang):
    """ID pemain yang namanya ada di susunan resmi laga terdekat.

    Set kosong kalau susunannya belum terbit — dan itu keadaan normal, bukan
    kegagalan. Penarik kita baru mendapat susunan pada atau sesudah kick-off,
    jadi aturan 4 memang jarang menyala sebelum laga. Fungsinya tetap ditulis
    supaya begitu ada sumber susunan pra-kickoff, aturannya langsung berlaku
    tanpa mengubah logika di atas.
    """
    from django.db.models import Q

    from matches.models import Match, PlayerMatchStatistics

    laga = (
        Match.objects.filter(Q(home_team=team) | Q(away_team=team))
        .filter(kickoff_at__gte=sekarang - JENDELA_SUSUNAN)
        .order_by('kickoff_at')
        .first()
    )
    if laga is None or laga.kickoff_at > sekarang + JENDELA_SUSUNAN:
        return set(), None
    ids = set(
        PlayerMatchStatistics.objects.filter(match=laga, team=team, starter=True)
        .values_list('player_id', flat=True)
    )
    return ids, (laga if ids else None)


def rekonsiliasi(pemain, sekarang):
    """Status akhir seluruh skuad + daftar konflik yang menunggu keputusan.

    Return (baris, konflik). `baris` urut nama; `konflik` cuma pemain yang
    sumbernya berselisih DAN belum diputuskan — itu yang naik ke panel SQ-01.
    """
    from players.models import AvailabilityDecision

    pemain = list(pemain)
    ids = [p.pk for p in pemain]

    entri = {}
    for e in PlayerAvailability.objects.filter(player_id__in=ids):
        entri.setdefault(e.player_id, []).append(e)

    keputusan = {
        d.player_id: d for d in AvailabilityDecision.objects.filter(player_id__in=ids)
    }

    team = pemain[0].team if pemain else None
    id_susunan, laga_susunan = susunan_resmi(team, sekarang) if team else (set(), None)

    baris, konflik = [], []
    for p in pemain:
        milik = entri.get(p.pk, [])
        hasil = putuskan(
            milik,
            keputusan=keputusan.get(p.pk),
            lewat_susunan_resmi=p.pk in id_susunan,
        )
        label, kelas = pill(hasil)
        row = {
            'player': p,
            'entri': sorted(milik, key=lambda e: e.source),
            'hasil': hasil,
            'label': label,
            'kelas': kelas,
            'keputusan': keputusan.get(p.pk),
            'aman_untuk_konten': hasil['asal'] != 'bentrok',
            'perkiraan_kembali': next(
                (e.expected_return for e in berklaim(milik) if e.expected_return), None
            ),
        }
        baris.append(row)
        if hasil['asal'] == 'bentrok':
            konflik.append(
                {
                    'player': p,
                    'pilihan': [
                        {
                            'entri': e,
                            'sumber': e.source,
                            'label_sumber': label_sumber(e.source),
                            'status_label': e.get_status_display(),
                            'umur': umur_teks(e.source_updated_at, sekarang),
                            'catatan': e.note,
                            'chance_pct': e.chance_pct,
                        }
                        for e in berklaim(milik)
                    ],
                }
            )

    baris.sort(key=lambda r: r['player'].name)
    konflik.sort(key=lambda k: k['player'].name)
    return baris, konflik, laga_susunan


def sumber_terpakai(baris):
    """Berapa sumber berbeda yang benar-benar menyumbang klaim — angka yang
    diminta muncul di header tabel SQ-02."""
    s = set()
    for r in baris:
        s.update(e.source for e in berklaim(r['entri']))
    return sorted(s)


def terakhir_diperbarui(baris):
    waktu = [e.fetched_at for r in baris for e in r['entri'] if e.fetched_at]
    return max(waktu) if waktu else None
