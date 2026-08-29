"""Laporan Pertandingan — paragraf otomatis dari data laga.

Kriteria selesai Tahap 4 di handoff: *"laporan satu laga lama bisa dihasilkan
tanpa campur tangan manual"*. Jadi modul ini tidak boleh punya satu pun
kalimat yang butuh diisi manusia.

**Aturan yang dipegang di sini.**

*Tidak ada klausa tanpa data.* Tiap potongan kalimat dibangun cuma kalau
angkanya ada. Laporan yang bilang "tanpa tembakan tepat sasaran" padahal
kolomnya null bukan laporan, itu karangan. Konsekuensinya paragraf jadi
pendek untuk laga yang datanya tipis — dan itu memang yang seharusnya
terlihat.

*Tidak ada penilaian.* Modul ini tidak menulis "tampil buruk" atau "layak
dipuji". Dia menyebut angka dan seberapa jauh angka itu dari kebiasaan, lalu
berhenti. Penilaian pekerjaan analis, dan kalau app yang menuliskannya, kutipan
yang beredar jadi pendapat mesin yang menyamar sebagai data.

*Angka tidak pernah ditulis ulang.* Teks angka datang dari `key_numbers`
apa adanya, format yang sama dengan yang tampil di kartu, supaya laporan dan
kartu tidak pernah bisa berbeda.

`varian` dipakai tombol **Susun ulang**: susunan kalimat berubah, angkanya
tidak. Menyusun ulang tidak boleh mengubah fakta apa pun — kalau bisa, salah
satu dari dua versi itu bohong.
"""

from matches import scoreline

JUMLAH_VARIAN = 3


def _daftar(nama):
    """'A', 'A dan B', 'A, B, dan C'."""
    nama = list(nama)
    if not nama:
        return ''
    if len(nama) == 1:
        return nama[0]
    if len(nama) == 2:
        return f'{nama[0]} dan {nama[1]}'
    return f'{", ".join(nama[:-1])}, dan {nama[-1]}'


def _menit(ev):
    if ev.extra_minute:
        return f"{ev.minute}+{ev.extra_minute}'"
    return f"{ev.minute}'"


def identitas(match):
    tim, lawan, kandang = scoreline.sudut_pandang(match)
    return {
        'judul': scoreline.judul_laga(match),
        'skor': scoreline.skor_teks(match),
        'hasil': scoreline.hasil(match),
        'lawan': lawan,
        'kandang': kandang,
        'kompetisi': match.league_name or '',
        'tanggal': match.kickoff_at,
        'venue': match.venue or '',
        'wasit': match.referee or '',
    }


def judul(match, gol_mu, gol_lawan, varian=0):
    """Satu kalimat kepala. Selalu memuat hasil dan lawannya."""
    _, lawan, kandang = scoreline.sudut_pandang(match)
    mu_gol, lawan_gol = scoreline.skor(match)
    h = scoreline.hasil(match)
    if h is None or lawan is None:
        return scoreline.judul_laga(match) or 'Laporan pertandingan'

    tempat = 'di kandang' if kandang else 'di markas lawan'
    nama = lawan.short_name or lawan.name
    kata = scoreline.HASIL_KATA[h]

    if h == 'D':
        inti = f'United ditahan {nama} {mu_gol}–{lawan_gol} {tempat}'
    else:
        inti = f'United {kata} {mu_gol}–{lawan_gol} atas {nama} {tempat}'
        if h == 'L':
            inti = f'United {kata} {mu_gol}–{lawan_gol} dari {nama} {tempat}'

    if varian % JUMLAH_VARIAN == 1 and gol_mu:
        pencetak = _daftar(sorted({g.player.name.split()[-1] for g in gol_mu if g.player}))
        if pencetak:
            return f'{inti}, gol dari {pencetak}'
    if varian % JUMLAH_VARIAN == 2 and match.league_name:
        return f'{inti} di {match.league_name}'
    return inti


def paragraf_jalannya(match, gol_mu, gol_lawan):
    """Paragraf 1 — apa yang terjadi, urut menit."""
    kalimat = []
    mu_gol, lawan_gol = scoreline.skor(match)
    _, lawan, kandang = scoreline.sudut_pandang(match)
    nama_lawan = (lawan.short_name or lawan.name) if lawan else 'lawan'

    if mu_gol is not None:
        kalimat.append(
            f'{scoreline.nama_laga(match)} '
            f'{"di kandang" if kandang else "di markas " + nama_lawan}'
            f'{", " + match.venue if match.venue else ""}, '
            f'berakhir {mu_gol}–{lawan_gol}.'
        )

    if gol_mu:
        potongan = [
            f'{g.player.name} {_menit(g)}' if g.player else f'gol {_menit(g)}'
            for g in gol_mu
        ]
        kalimat.append(f'Gol United datang lewat {_daftar(potongan)}.')
    elif mu_gol == 0:
        kalimat.append('United tidak mencetak gol.')

    if gol_lawan:
        potongan = [
            f'{g.player.name} {_menit(g)}' if g.player else f'gol {_menit(g)}'
            for g in gol_lawan
        ]
        kalimat.append(f'{nama_lawan} membalas lewat {_daftar(potongan)}.')
    elif lawan_gol == 0 and mu_gol is not None:
        kalimat.append('Gawang United tidak kebobolan.')

    return ' '.join(kalimat)


def paragraf_angka(angka, terbaik, varian=0):
    """Paragraf 2 — angka yang paling menyimpang, lalu pemain dengan nilai
    tertinggi. Kosong kalau tidak ada angka yang bisa dipertanggungjawabkan."""
    kalimat = []
    if angka:
        urut = angka if varian % JUMLAH_VARIAN != 2 else list(reversed(angka))
        utama = urut[0]
        kalimat.append(
            f'Angka yang paling jauh dari kebiasaan musim ini: '
            f'{utama["label"].lower()} {utama["nilai_teks"]}, '
            f'{utama["simpangan_teks"]} ({utama["pembanding"]}).'
        )
        if len(urut) > 1:
            lain = urut[1]
            kalimat.append(
                f'Menyusul {lain["label"].lower()} {lain["nilai_teks"]} '
                f'({lain["pembanding"]}).'
            )

    if terbaik and terbaik.get('nilai') is not None:
        kontribusi = ', '.join(terbaik['kontribusi'])
        ekor = f' — {kontribusi}' if kontribusi else ''
        kalimat.append(
            f'Nilai tertinggi versi hitungan kami jatuh ke {terbaik["player"].name} '
            f'({terbaik["teks"]}){ekor}.'
        )

    return ' '.join(kalimat)


def susun(match, angka, nilai_pemain, gol_mu, gol_lawan, varian=0):
    """Laporan lengkap. Fungsi murni — semua data sudah dikumpulkan pemanggil."""
    terbaik = next((r for r in nilai_pemain if r.get('tertinggi')), None)
    paragraf = [
        paragraf_jalannya(match, gol_mu, gol_lawan),
        paragraf_angka(angka, terbaik, varian=varian),
    ]
    return {
        'identitas': identitas(match),
        'judul': judul(match, gol_mu, gol_lawan, varian=varian),
        'paragraf': [p for p in paragraf if p],
        'varian': varian % JUMLAH_VARIAN,
        # Disebut eksplisit di UI: laporan ini mesin yang menulis, dan dia
        # cuma sekuat data yang mengisinya.
        'lengkap': bool(angka) and any(r.get('nilai') is not None for r in nilai_pemain),
    }


def teks_polos(laporan):
    """Versi yang disalin tombol `Salin laporan`."""
    bagian = [laporan['judul'], '']
    bagian.extend(laporan['paragraf'])
    ident = laporan['identitas']
    ekor = ' · '.join(
        b for b in [ident['kompetisi'], ident['venue'], str(ident['tanggal'].date())] if b
    )
    if ekor:
        bagian.extend(['', ekor])
    return '\n'.join(bagian)
