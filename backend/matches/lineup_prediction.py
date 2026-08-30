"""Prediksi susunan MU dari susunan laga-laga sebelumnya.

Logika murni — nggak nyentuh jaringan, nggak nulis DB. Polanya niru
`momentum.py`: konstanta + fungsi bebas, biar bisa dites tanpa fixture besar
dan tanpa mock jaringan. Command `predict_lineup` cuma pembungkus tipis.

**Dari mana datanya.** `PlayerMatchStatistics.formation_x/formation_y` diisi
FotMob dan cuma ada buat 11 pemain yang MAIN DARI AWAL — itu yang bikin kita
tahu siapa starter tanpa perlu field `is_starter` (yang memang nggak ada di
model ini; kolom `starter` pernah dicoba dan isinya 0 buat semua baris).

**Apa arti persentasenya, dan apa yang BUKAN.** Angka keyakinan di sini itu
**frekuensi historis slot** — 'pemain ini ngisi slot ini di 4 dari 5 laga
terakhir' = 80. Itu BUKAN peluang dia main Sabtu nanti. Kita nggak punya dasar
buat ngitung peluang: data cedera seluruhnya berstatus RETURNED (nggak ada
sinyal ketersediaan sama sekali), rotasi nggak terekam, skorsing nggak terekam,
dan bursa transfer nggak terekam. Bilang '80% kemungkinan start' itu bakal
jadi angka yang kelihatan meyakinkan tapi nggak berdasar — persis jenis
kesalahan yang bikin analis berhenti percaya sama app-nya. Teks di `note`
menyebut batas ini eksplisit, dan UI harus ikut menyebutnya.
"""

import re
from collections import Counter, defaultdict

# Dua slot dianggap sebaris kalau jarak x-nya di bawah ini. Koordinat FotMob
# ternormalisasi 0..1, dan baris formasi biasanya berjarak jauh lebih besar.
LINE_TOLERANCE = 0.05

# Jendela default: 5 laga terakhir. Cukup panjang buat ngeredam rotasi satu
# laga, cukup pendek biar nggak nyeret susunan dari era pelatih sebelumnya.
DEFAULT_WINDOW = 5

# Di bawah ini, persentase apa pun nggak layak dicetak — 'ngisi slot di 2 dari
# 2 laga' itu 100% yang nggak berarti apa-apa.
MIN_EFFECTIVE = 3

# Pagar kalau FotMob ganti skala koordinat. Ini kejadian nyata di repo ini:
# `field_x` ESPN pernah campur 0..1 dan 0..100 dalam satu tabel.
COORD_RANGE = (0.0, 1.0)

# Status yang artinya laganya beneran udah dimainkan.
_FINAL = ('FT', 'AET', 'PEN')


def read_xi(match, team):
    """11 slot berkoordinat buat satu tim di satu laga, atau None.

    Sengaja balikin None (bukan daftar pendek) kalau jumlahnya bukan 11:
    `pull_fotmob` nyocokin slot lewat external ref FotMob, dan kalau ref-nya
    nggak ketemu slot itu hilang TANPA error. Laga dengan 10 slot itu data
    yang bolong, bukan formasi 10 pemain — dipakai separuh malah bikin baris
    formasinya salah baca.
    """
    from matches.models import PlayerMatchStatistics

    rows = list(
        PlayerMatchStatistics.objects.filter(
            match=match, team=team, formation_x__isnull=False, formation_y__isnull=False
        ).select_related('player')
    )
    if len(rows) != 11:
        return None

    lo, hi = COORD_RANGE
    for r in rows:
        if not (lo <= r.formation_x <= hi and lo <= r.formation_y <= hi):
            return None

    return [
        {
            'x': r.formation_x,
            'y': r.formation_y,
            'player_id': r.player_id,
            'player': r.player,
            'minutes': r.minutes_played,
        }
        for r in rows
    ]


def split_lines(slots):
    """Kelompokkan 11 slot jadi baris formasi, dari belakang ke depan.

    Pengelompokannya RELATIF (jarak antar slot berurutan), bukan ambang
    absolut. Nilai x FotMob nyebar tergantung jumlah baris — formasi 4 baris
    naruh lini tengah di tempat yang beda dari formasi 3 baris — jadi ambang
    tetap kayak 'x < 0.3 berarti bek' bakal salah di sebagian formasi.
    """
    urut = sorted(slots, key=lambda s: s['x'])
    baris, sekarang = [], [urut[0]]
    for slot in urut[1:]:
        if slot['x'] - sekarang[-1]['x'] >= LINE_TOLERANCE:
            baris.append(sekarang)
            sekarang = [slot]
        else:
            sekarang.append(slot)
    baris.append(sekarang)
    # y kecil = kiri. Diverifikasi dari data: Luke Shaw (bek kiri) y=0.125,
    # Mazraoui (bek kanan) y=0.875 di laga yang sama.
    return [sorted(b, key=lambda s: s['y']) for b in baris]


def formation_signature(lines):
    """'4-2-3-1' dari daftar baris (baris kiper nggak ikut dihitung)."""
    return '-'.join(str(len(b)) for b in lines[1:])


def label_lines(lines):
    """Label posisi buat tiap slot, urut belakang→depan lalu kiri→kanan."""
    labels = []
    n_baris = len(lines)

    for i, baris in enumerate(lines):
        n = len(baris)

        if i == 0:
            labels.extend(['GK'] * n)
        elif i == 1:
            # Lini belakang.
            if n >= 4:
                labels.extend(['LB'] + ['CB'] * (n - 2) + ['RB'])
            else:
                labels.extend(['CB'] * n)
        elif i == n_baris - 1:
            # Lini terdepan.
            if n == 1:
                labels.append('CF')
            elif n == 2:
                labels.extend(['CF', 'CF'])
            else:
                labels.extend(['LW'] + ['CF'] * (n - 2) + ['RW'])
        else:
            # Lini tengah. Ada berapa baris tengah, dan ini yang keberapa?
            # (n_baris dikurangi kiper, lini belakang, dan lini depan.)
            baris_tengah = n_baris - 3
            urutan = i - 2  # 0 = baris tengah paling belakang

            if baris_tengah <= 1:
                inti = 'CM'          # satu-satunya lini tengah, mis. 4-4-2
            elif urutan == 0:
                inti = 'DM'          # paling belakang, mis. double pivot 4-2-3-1
            elif urutan == baris_tengah - 1:
                inti = 'AM'          # paling depan, mis. lini '3' di 4-2-3-1
            else:
                inti = 'CM'

            # n <= 2 itu justru kasus PALING SERING (double pivot di 4-2-3-1),
            # dan versi pertama aturan ini nggak menanganinya sama sekali.
            if n <= 2:
                labels.extend([inti] * n)
            elif n == 3 and inti != 'AM':
                # Lini tengah 3 yang BUKAN band menyerang itu sentral semua
                # (4-3-3). Yang jadi sayap cuma band menyerang di 4-2-3-1,
                # dan itu ditangani cabang di bawah lewat inti == 'AM'.
                labels.extend([inti] * 3)
            else:
                # Pemain terluar di lini tengah lebar itu sayap ATAU wing-back,
                # dan bedanya ditentukan lini belakang: kalau di belakang udah
                # ada 4 orang (LB/RB terisi), yang lebar ini sayap. Kalau di
                # belakang cuma 3, merekalah yang jadi bek sayap.
                #
                # Enum posisi nggak punya LWB/RWB, jadi wing-back dipetakan ke
                # LB/RB — cukup buat menggambar, dan nggak perlu migrasi cuma
                # buat dua label.
                bek_lebar = len(lines[1]) >= 4
                kiri, kanan = ('LW', 'RW') if bek_lebar else ('LB', 'RB')
                labels.extend([kiri] + [inti] * (n - 2) + [kanan])

    return labels


def slot_keys(labels):
    """Kunci unik per slot: 'CB1', 'CB2', ... biar bisa dihitung lintas laga."""
    total = Counter(labels)
    jalan = Counter()
    keys = []
    for label in labels:
        if total[label] == 1:
            keys.append(label)
        else:
            jalan[label] += 1
            keys.append(f'{label}{jalan[label]}')
    return keys


def recent_xis(team, before, window=DEFAULT_WINDOW):
    """Susunan `window` laga terakhir tim ini sebelum `before`.

    Laga yang datanya bolong dilewati dan diganti laga yang lebih tua, jadi
    jendelanya tetap berisi `window` susunan utuh selama datanya ada.
    """
    from django.db.models import Q

    from matches.models import Match

    qs = (
        Match.objects.filter(Q(home_team=team) | Q(away_team=team))
        .filter(status__in=_FINAL, kickoff_at__lt=before)
        .order_by('-kickoff_at')
    )

    hasil = []
    for match in qs[: window * 4]:  # cadangan buat laga yang datanya bolong
        slots = read_xi(match, team)
        if slots is None:
            continue
        lines = split_lines(slots)
        hasil.append(
            {
                'match': match,
                'lines': lines,
                'formation': formation_signature(lines),
                'labels': label_lines(lines),
                'slots': [s for baris in lines for s in baris],
            }
        )
        if len(hasil) >= window:
            break
    return hasil


def predict_xi(team, before, window=DEFAULT_WINDOW):
    """Prediksi susunan dari susunan-susunan sebelumnya.

    Return dict berisi `formation`, `slots` (11 buah), `n_efektif`,
    `matches_used`, dan `warnings`. Kalau nggak ada data sama sekali,
    `slots` kosong dan `warnings` menjelaskan kenapa.
    """
    riwayat = recent_xis(team, before, window)
    peringatan = []

    if not riwayat:
        return {
            'formation': '',
            'slots': [],
            'n_efektif': 0,
            'matches_used': [],
            'warnings': ['Nggak ada satu pun laga dengan susunan berkoordinat.'],
        }

    # Formasi yang paling sering dipakai. Laga dengan formasi lain DIBUANG dari
    # perhitungan slot — slot 'DM2' di 4-2-3-1 bukan slot yang sama dengan
    # 'DM2' di 3-5-2, jadi mencampurnya bikin frekuensinya bohong.
    hitung_formasi = Counter(r['formation'] for r in riwayat)
    formasi, _ = hitung_formasi.most_common(1)[0]
    dipakai = [r for r in riwayat if r['formation'] == formasi]
    dibuang = len(riwayat) - len(dipakai)
    if dibuang:
        peringatan.append(
            f'{dibuang} laga dibuang karena formasinya beda '
            f'({", ".join(f + " x" + str(n) for f, n in hitung_formasi.items() if f != formasi)}).'
        )

    n_efektif = len(dipakai)
    if n_efektif < MIN_EFFECTIVE:
        peringatan.append(
            f'Cuma {n_efektif} laga berformasi {formasi} — di bawah {MIN_EFFECTIVE}, '
            f'jadi persentasenya nggak dicetak.'
        )

    # Siapa yang ngisi tiap slot, per laga.
    per_slot = defaultdict(Counter)
    posisi_slot = {}
    koordinat = defaultdict(list)
    menit = Counter()
    for r in dipakai:
        keys = slot_keys(r['labels'])
        for key, label, slot in zip(keys, r['labels'], r['slots']):
            per_slot[key][slot['player_id']] += 1
            posisi_slot[key] = label
            koordinat[key].append((slot['x'], slot['y']))
            if slot['minutes'] is not None:
                menit[slot['player_id']] += slot['minutes']

    pemain_by_id = {
        s['player_id']: s['player'] for r in dipakai for s in r['slots']
    }

    # Pemain kunci = 5 menit terbanyak. Dilewati kalau ada baris tanpa menit,
    # karena meranking di atas data separuh itu bikin urutan yang bohong.
    menit_lengkap = all(
        s['minutes'] is not None for r in dipakai for s in r['slots']
    )
    kunci = set()
    if menit_lengkap and menit:
        kunci = {pid for pid, _ in menit.most_common(5)}
    elif not menit_lengkap:
        peringatan.append('Penandaan pemain kunci dilewati: ada baris tanpa menit main.')

    urutan_slot = slot_keys(dipakai[0]['labels'])
    hasil, terpakai = [], set()
    for nomor, key in enumerate(urutan_slot, start=1):
        pilihan = per_slot[key].most_common()
        pemain_id = None
        n = 0
        for kandidat_id, jumlah in pilihan:
            if kandidat_id not in terpakai:
                pemain_id, n = kandidat_id, jumlah
                break
        if pemain_id is None and pilihan:
            pemain_id, n = pilihan[0]
            peringatan.append(f'Slot {key} nggak dapat pemain unik.')
        if pemain_id is not None:
            terpakai.add(pemain_id)

        xs = koordinat[key]
        hasil.append(
            {
                'slot': nomor,
                'position': posisi_slot[key],
                'player': pemain_by_id.get(pemain_id),
                # None = yakin (selalu ngisi slot ini). Terisi = frekuensi
                # historis, BUKAN peluang start.
                'confidence_pct': (
                    None
                    if (n == n_efektif or n_efektif < MIN_EFFECTIVE)
                    else round(100 * n / n_efektif)
                ),
                'is_key': pemain_id in kunci,
                'pitch_x': round(sum(x for x, _ in xs) / len(xs), 4) if xs else None,
                'pitch_y': round(sum(y for _, y in xs) / len(xs), 4) if xs else None,
                'frekuensi': f'{n}/{n_efektif}',
            }
        )

    return {
        'formation': formasi,
        'slots': hasil,
        'n_efektif': n_efektif,
        'matches_used': [r['match'] for r in dipakai],
        'warnings': peringatan,
    }


def build_note(prediksi, window):
    """Jejak audit buat `PredictionSnapshot.note`.

    Sengaja panjang: snapshot ini bakal dibaca berbulan-bulan kemudian waktu
    ngevaluasi Cek Prediksi, dan yang paling gampang disalahpahami justru arti
    persentasenya.
    """
    baris = [
        f'Dibuat otomatis oleh predict_lineup (jendela {window} laga).',
        f'Formasi: {prediksi["formation"]} · dasar {prediksi["n_efektif"]} laga.',
        '',
        'Laga yang dipakai:',
    ]
    for m in prediksi['matches_used']:
        baris.append(f'  {m.kickoff_at:%Y-%m-%d} {m.home_team.name} vs {m.away_team.name}')
    baris += ['', 'Frekuensi per slot:']
    for s in prediksi['slots']:
        nama = s['player'].name if s['player'] else '(kosong)'
        baris.append(f'  {s["position"]:<3} {nama} {s["frekuensi"]}')
    if prediksi['warnings']:
        baris += ['', 'Catatan:'] + [f'  - {w}' for w in prediksi['warnings']]
    baris += [
        '',
        'BATAS YANG HARUS DIBACA SEBELUM MEMAKAI ANGKA INI:',
        '- Persentase = frekuensi historis slot, BUKAN peluang pemain start.',
        '- Ketersediaan pemain tidak diperhitungkan sama sekali: seluruh entri',
        '  Injury pemain aktif berstatus RETURNED, jadi tidak ada sinyal cedera.',
        '- Rotasi, skorsing, dan transfer tidak terekam di data mana pun.',
    ]
    return '\n'.join(baris)


# Possession di luar rentang ini itu data rusak, bukan dominasi ekstrem.
# Kejadian nyata: laga pramusim lawan Wrexham tercatat possession 100% dengan
# 0 tembakan tepat sasaran. Nilai begitu kalau ikut dirata-rata bakal bikin
# ambang klaim ngaco.
POSSESSION_WAJAR = (5, 95)


# Desain PR-03 minta TIGA kartu. Kandidat boleh lebih banyak — itu gunanya
# kandidat — tapi yang dipertaruhkan dibatasi tiga. Panel berisi enam dugaan
# bukan analisis, itu daftar kemungkinan.
MAKS_HIPOTESIS = 3


def suggest_hypotheses(team, before, window=DEFAULT_WINDOW):
    """Kandidat hipotesis dari pola data — BAHAN, bukan klaim final.

    Handoff tegas: *"App tidak menyimpulkan, dia menyiapkan bukti. Kesimpulan
    tetap dari analis."* Jadi yang dihasilkan di sini kandidat yang sudah
    membawa angka dasarnya dan sudah punya kriteria cek yang bisa dijalankan
    sesudah laga. Analis yang memutuskan mana yang dipertaruhkan.

    Tiap kandidat cuma dibikin kalau dasarnya ADA. Kalau statistik yang
    dibutuhkan kosong, kandidatnya nggak muncul sama sekali — lebih baik dua
    kandidat berdasar daripada lima yang satu di antaranya karangan.
    """
    from django.db.models import Q

    from matches.models import Match, MatchEvent, MatchShot, MatchTeamStatistics

    laga = list(
        Match.objects.filter(Q(home_team=team) | Q(away_team=team))
        .filter(status__in=_FINAL, kickoff_at__lt=before)
        .order_by('-kickoff_at')[:window]
    )
    if not laga:
        return []

    ids = [m.pk for m in laga]
    kandidat = []

    # 1. Formasi — paling bisa dicek persis.
    formasi = Counter()
    for m in laga:
        f = m.home_formation if m.home_team_id == team.pk else m.away_formation
        if f:
            formasi[f] += 1
    if formasi:
        top, n = formasi.most_common(1)[0]
        if n >= 2:
            kandidat.append({
                'text': f'MU turun dengan formasi {top}.',
                'evidence_note': (
                    f'Dasar: {n} dari {len(laga)} laga terakhir pakai {top}. '
                    f'[cek:formasi={top}]'
                ),
            })

    stats = list(MatchTeamStatistics.objects.filter(match_id__in=ids, team=team))

    # 2. Tembakan tepat sasaran.
    sot = [s.shots_on_target for s in stats if s.shots_on_target is not None]
    if len(sot) >= 3:
        rata = sum(sot) / len(sot)
        ambang = max(1, round(rata))
        kandidat.append({
            'text': f'MU melepas minimal {ambang} tembakan tepat sasaran.',
            'evidence_note': (
                f'Dasar: rata-rata {rata:.1f} dari {len(sot)} laga '
                f'(rentang {min(sot)}-{max(sot)}). [cek:shots_on_target>={ambang}]'
            ),
        })

    # 3. Possession — cuma kalau datanya waras.
    pos = [
        s.possession_pct for s in stats
        if s.possession_pct is not None
        and POSSESSION_WAJAR[0] <= s.possession_pct <= POSSESSION_WAJAR[1]
    ]
    dibuang = len([s for s in stats if s.possession_pct is not None]) - len(pos)
    if len(pos) >= 3:
        rata = sum(pos) / len(pos)
        ambang = round(rata / 5) * 5
        catatan = f'Dasar: rata-rata {rata:.0f}% dari {len(pos)} laga'
        if dibuang:
            catatan += f' ({dibuang} laga dibuang karena angkanya nggak masuk akal)'
        kandidat.append({
            'text': f'MU menguasai bola minimal {ambang}%.',
            'evidence_note': f'{catatan}. [cek:possession_pct>={ambang}]',
        })

    # 4. Gol.
    gol = [
        MatchEvent.objects.filter(match=m, team=team, event_type=MatchEvent.EventType.GOAL).count()
        for m in laga
    ]
    if gol:
        rata = sum(gol) / len(gol)
        kandidat.append({
            'text': 'MU mencetak minimal 2 gol.' if rata >= 1.5 else 'MU mencetak minimal 1 gol.',
            'evidence_note': (
                f'Dasar: rata-rata {rata:.1f} gol per laga dari {len(gol)} laga '
                f'({"-".join(str(g) for g in gol)}). [cek:gol>={2 if rata >= 1.5 else 1}]'
            ),
        })

    # 5. xG — cuma laga Premier League yang punya (cakupan Understat).
    xg_per_laga = []
    for m in laga:
        nilai = [s.xg for s in MatchShot.objects.filter(match=m, team=team) if s.xg]
        if nilai:
            xg_per_laga.append(sum(nilai))
    if len(xg_per_laga) >= 2:
        rata = sum(xg_per_laga) / len(xg_per_laga)
        ambang = round(rata * 2) / 2  # bulatkan ke 0,5 terdekat
        kandidat.append({
            'text': f'xG MU di atas {ambang:.1f}.',
            'evidence_note': (
                f'Dasar: rata-rata {rata:.2f} dari {len(xg_per_laga)} laga yang punya xG. '
                f'Cuma laga Premier League yang punya (cakupan Understat). '
                f'[cek:xg>{ambang:.1f}]'
            ),
        })

    return kandidat



# Penanda kriteria yang bisa dibaca mesin, ditempel di `evidence_note` waktu
# kandidat dibuat: '[cek:shots_on_target>=6]'.
#
# Kenapa penanda di teks, bukan kolom terstruktur: hipotesis yang DITULIS
# ANALIS SENDIRI nggak akan pernah punya kolom itu terisi, dan memaksa analis
# ngisi formulir kriteria bakal bikin fitur ini nggak kepakai. Dengan penanda,
# kandidat yang app hasilkan bisa dinilai otomatis, dan kalimat bebas analis
# tetap masuk apa adanya — cuma statusnya tetap BELUM sampai dinilai manual.
# App nggak pura-pura ngerti kalimat yang nggak dia tulis.
CEK_PATTERN = re.compile(r'\[cek:(\w+)(>=|>|=)([\w.\-]+)\]')


def baca_kriteria(evidence_note):
    """(metrik, operator, ambang) dari penanda, atau None kalau nggak ada."""
    m = CEK_PATTERN.search(evidence_note or '')
    if not m:
        return None
    metrik, op, ambang = m.groups()
    try:
        ambang = float(ambang)
    except ValueError:
        pass  # formasi: ambangnya string, mis. '4-2-3-1'
    return metrik, op, ambang
