# Checklist Implementasi — MU Analytics

Status tiap butir design handoff terhadap kode yang benar-benar ada.
Diaudit **24 Agustus 2026** dengan membaca file, bukan menebak dari nama.
Diperbarui sesudah halaman Pra-laga, penyambungan provenance, dan LV-08.

Keterangan status: **✅ selesai** · **🟡 sebagian** · **⬜ belum** · **🚫 terblokir**

> Angka di sini dari **produksi**, bukan DB lokal. Sumber keputusan & jebakan
> ada di [CATATAN-PERUBAHAN-BESAR.md](CATATAN-PERUBAHAN-BESAR.md).

---

## Ringkasan

| Tahap | ✅ | 🟡 | ⬜ | 🚫 | Keadaan |
|---|--:|--:|--:|--:|---|
| 0 — Fondasi data | 6 | 7 | 5 | 0 | Tulang punggung berdiri; separuh entitas belum ada |
| 1 — Penarikan & rekonsiliasi | 7 | 4 | 1 | 1 | **Chip sumber & Kesehatan Sumber akhirnya tampil** |
| 2 — Halaman rujukan | 8 | 6 | 6 | 3 | **Statistik selesai**; Skuad separuh; Berita nol |
| 3 — Metrik turunan | 1 | 1 | 4 | 1 | **LV-08 beban 14 hari jadi**, dirujuk 3 kartu |
| 4 — Pasca laga | 0 | 0 | 7 | 0 | **Nol baris kode** |
| 5 — Pra laga | 5 | 1 | 5 | 0 | **Halaman Pra-laga hidup** — PR-01/02/03/04/05 |
| 6 — Live | 0 | 3 | 9 | 0 | Belum dimulai |
| Lintas halaman | 3 | 4 | 4 | 0 | Chip sumber, Kesehatan Sumber, Konflik tampil |

**220 test lulus.** Tujuh halaman hidup: `/`, `/jadwal/`, `/pra/`, `/skuad/`, `/statistik/`, `/cedera/`, `/match/<id>/`.

---

## Tahap 0 — Fondasi data

| | Butir | Catatan |
|---|---|---|
| ✅ | `Match` + `MatchExternalRef` + `resolve_match` | 817 laga, 8 musim |
| ✅ | `Player` | Skuad MU aktif 38 |
| ✅ | `PlayerMatchStatistics` | ~90 kolom, 27.824 baris |
| ✅ | `Hypothesis` + prediksi bercap waktu pra-kickoff | `created_at` = `auto_now_add`, ada test regresi |
| ✅ | **Pemetaan ID lintas provider** (handoff: "pekerjaan wajib pertama") | Harry Maguire menyatu dari 8 sumber |
| ✅ | Jejak sumber per angka (`field_sources`) | **27.824/27.824 = 100%** |
| 🟡 | `MatchEvent` dengan koordinat x/y | Koordinat ada di `MatchPlay`/`MatchShot`, bukan di `MatchEvent`. **Tidak ada event umpan sama sekali** — pass network mustahil dari data ini |
| 🟡 | `Lineup` | Tertanam di `PlayerMatchStatistics`; tidak ada tempat menyimpan waktu terbit susunan resmi |
| 🟡 | `Injury/Availability` | Sisi *availability* belum ada: skorsing, pinjaman, beban menit, status `Bentrok` |
| 🟡 | `SourceHealth` | Fungsinya ada di `matches/source_health.py` tapi **tidak pernah dipanggil dari mana pun** |
| 🟡 | Tabel `source` | Cuma enum `DataSource`; ambang kesegaran ter-hardcode |
| 🟡 | Tabel `ingest_log` | `MatchIngest` itu keadaan terakhir, bukan log. `rows` kini omong kosong |
| 🟡 | Syarat selesai B: tidak ada nama ganda | **60 kunci nama aktif masih muncul >1×** (mayoritas orang berbeda) |
| ⬜ | `PlayerSeasonStats` (per kompetisi per musim) | Diagregasi on-the-fly; tanpa ini tidak ada dasar pembanding se-liga |
| ⬜ | `TransferRumour` | App `transfers/` masih stub Django |
| ⬜ | `NewsItem` | Nol rujukan di seluruh backend |
| ⬜ | `SavedMoment` | Nol rujukan |
| ⬜ | Model `Competition` | `matches/competitions.py` sengaja fungsi murni, bukan model |

## Tahap 1 — Penarikan & rekonsiliasi

| | Butir | Catatan |
|---|---|---|
| ✅ | Job penarikan per sumber | 17 command, 8 provider |
| ✅ | Aturan prioritas sumber | `players/provenance.py` |
| ✅ | Penyaring inkremental | ESPN 90 detik → 9 detik, ~670 panggilan/hari hilang |
| ✅ | Backup off-server | Harian ke Google Drive, terverifikasi restore-able |
| 🟡 | Jadwal per sumber | Hidup sebagai crontab di server, **tidak ada di repo** |
| 🟡 | Penyimpanan mentah (`RawPayload`) | Cuma 3 dari 17 command yang `store_raw` |
| 🟡 | Pendeteksi konflik | 150 `FieldConflict`, tapi cuma 2 command yang mencatat |
| 🟡 | Data se-liga untuk kalimat pembanding | Tidak ada agregat musim tersimpan |
| 🟡 | Test fondasi | `source_health.py` nol test |
| ✅ | **Chip `sumber: A+C` di UI** | Tampil di 42 baris Statistik |
| ✅ | Status kesegaran feed | Panel Kesehatan Sumber di semua halaman |
| ✅ | Denyut nadi sumber | `SourceHeartbeat` — feed sehat tanpa data baru bukan feed mati |
| ⬜ | Halaman Skuad menampilkan konflik | Kartu SQ-01 belum ada |
| ⬜ | Pilihan analis tersimpan | Tidak ada tempat menyimpannya |
| 🚫 | Konflik ketersediaan dari dua feed cedera | **Cuma Highlightly** — tidak ada yang bisa berselisih |

## Tahap 2 — Halaman rujukan

### Statistik — ✅ selesai
Filter musim (2 chip) ✅ · filter kompetisi ✅ · sortir dua arah ✅ · baris kosong
selalu di bawah ✅ · keterangan total vs per-90 ✅ · **kriteria selesai handoff
terpenuhi & dibuktikan test** ✅

| | Butir | Catatan |
|---|---|---|
| 🟡 | Tabel 11 kolom | 10 dari 11 sesuai desain |
| 🟡 | Tanda "sampel kecil" | Desain minta baris **ditandai**; sekarang angkanya dikosongkan (`–`) |
| 🚫 | Kolom Prog/90 | Metrik progresif **tidak ada di FotMob, Understat, maupun ESPN**. Diganti "1/3 Akhir/90" dengan label jujur |

### Skuad — 🟡 halaman lama masih jalan
| | Butir | Catatan |
|---|---|---|
| ✅ | Kolom Pemain | |
| 🟡 | Kolom Pos, Status, Catatan, Perkiraan kembali | Belum di halaman Skuad; pill status belum ada |
| ⬜ | Rangka tabel 6 kolom sesuai desain | |
| ⬜ | Kolom Beban 14 hr + pewarnaan risiko | Datanya bisa dihitung, rumusnya (LV-08) belum ada |
| ⬜ | Header: waktu pembaruan + jumlah sumber | |
| 🚫 | **Panel Konflik Sumber (SQ-01)** | Terblokir sumber cedera kedua |
| 🚫 | Urutan prioritas sumber ketersediaan | Sama |

### Berita — ⬜ nol
Tidak ada model, route, maupun sumber. **Butuh keputusan produk dulu:
beritanya dari mana?** Tingkat A/B/C juga terblokir — ia butuh riwayat klaim
yang akhirnya terbukti, dan riwayat itu baru ada setelah feed berjalan lama.

## Tahap 3 — Metrik turunan

| | Butir | Catatan |
|---|---|---|
| ✅ | **Beban 14 hari (LV-08)** | `matches/workload.py`, fungsi murni bertes; tampil di Skuad |
| 🟡 | Momentum | Ada di `matches/momentum.py`, **tapi `build_momentum` sendiri belum punya test** |
| ⬜ | PPDA | Tidak ada yang memblokir versi per-laga |
| ⬜ | Nilai pemain (LV-06/PS-03) | Bobot per aksi belum ditetapkan |
| ⬜ | Bola kedua | Rumus belum dispesifikasikan, datanya juga tidak ada |
| 🚫 | xT (expected threat) | Butuh event umpan berkoordinat yang tidak kita punya |

## Tahap 4 — Pasca laga — ⬜ 0 dari 7

Nol baris kode. Halaman Pasca, Laporan Pertandingan, Angka Penentu (PS-02),
Nilai Pemain (PS-03), Saved Moments (PS-04), Generator Prompt (PS-05).

## Tahap 5 — Pra laga

| | Butir | Catatan |
|---|---|---|
| ✅ | Penyimpanan prediksi bercap waktu | `PredictionSnapshot` + `LineupSlot` + `HypothesisItem` |
| ✅ | Kriteria selesai handoff | Terpenuhi **di lapisan data** — 2 snapshot tersimpan pra-kickoff |
| ✅ | **Halaman Pra + Bar Identitas (PR-01)** | Dua mode: Menyiapkan laga / Laga berjalan |
| ✅ | **Prediksi Susunan (PR-02)** | Lapangan 11 node, orientasi TV, digambar tanpa aset |
| ✅ | **Cek Prediksi (PR-04)** | Kartu KENA/BELUM/MELESET, dinilai `evaluate_hypotheses` |
| ✅ | **Head to Head (PR-05)** | Skor selalu ditulis United dulu |
| 🟡 | Hipotesis Taktik (PR-03) | Tampil, tapi spesifikasi minta pola LAWAN dari 8 laga |
| ⬜ | Pemain Kunci (PR-06) | Butuh tolok ukur liga per posisi |
| ⬜ | Profil Lawan (PR-07) | Butuh PPDA + persentil |
| ⬜ | Duel Kunci (PR-08) | |
| ⬜ | Fakta Pendukung (PR-09) | |

## Tahap 6 — Live — ⬜ belum dimulai

Delapan komponen; tujuh belum ada, satu (Cek Prediksi) backend-nya matang
tanpa UI. Handoff tegas: **bangun mode putar ulang dulu, jangan mode langsung**.
`RawPayload` ada sebagai bahan, tapi **tidak ada satu pun pembacanya**.

## Lintas halaman

| | Butir | Catatan |
|---|---|---|
| ✅ | Jejak sumber per field | Datanya 100%, **dan sekarang tampil** |
| ✅ | Panel Kesehatan Sumber | Di semua halaman, dengan denyut nadi |
| ✅ | Konflik antar sumber ditandai | Kartu Konflik di Statistik |
| 🟡 | Rangka aplikasi | Rel nav kurang 4 halaman; belum ada bar atas |
| 🟡 | Design token | **Tipografi belum dipasang** — Google Fonts tidak dimuat |
| ⬜ | Konvensi skor: MU selalu ditulis lebih dulu | Belum ada helper terpusat |
| ⬜ | Indikator kekuatan bukti (3/3 · 2/3) | Prinsip desain no. 4 |
| ⬜ | Toggle tampil/sembunyi chip sumber | |
| ⬜ | Prinsip "tanpa aset" | |

---

## Yang direkomendasikan berikutnya

**1. Pipeline Berita.** Sumbernya sudah diriset dan diuji hidup (24 Agu):
Sky Sports feed khusus MU (`rss/11667`), Guardian Open Platform (gratis
non-komersial, 500/hari), Manchester Evening News, plus kanal YouTube resmi
klub dan Fabrizio Romano.

**Dua sumber harus dicoret, dan bukan karena teknis.** The Athletic melarang
eksplisit *"creating archived or cached data sets"* — itu persis
menggambarkan tabel berita kita, dan konsekuensinya **tidak ada jalur sah
untuk Ornstein** karena ia hanya menulis di sana. BBC melarang *"plucking
metadata from our RSS feeds"*. Keduanya larangan tertulis.

Tiga jebakan yang sudah teridentifikasi sebelum satu baris kode ditulis:
- **Kepemilikan bersama.** MEN, Mirror, Express, Daily Star semuanya Reach plc.
  Menghitungnya sebagai sumber terpisah bikin "6 sumber sepakat" bohong —
  hitung per **grup penerbit**.
- **Satu sumber asli, enam penyalin.** Mayoritas berita transfer mengutip
  Romano. Simpan `sumber_asal_dikutip`, bukan cuma jumlah.
- **Feed WordPress mengirim artikel UTUH** di `content:encoded`. Parser wajib
  membuangnya sebelum menyentuh DB, atau kita menyalin artikel tanpa sadar.

**2. Sumber cedera kedua: Fantasy Premier League API.** Gratis, tanpa key,
satu panggilan/hari, dan memberi ketiga hal yang desain minta: status, teks
kembali, umur data. Konfliknya sudah nyata — Amad Diallo dianggap bugar oleh
FotMob tapi *"75% chance of playing"* oleh FPL. Ini yang membuka panel
Konflik Sumber di Skuad.

Sekaligus menjawab misteri lama: **263 dari 264 entri RETURNED bukan bug
kita.** Highlightly ternyata feed **riwayat karier**, bukan ketersediaan —
entri terbaru Mason Mount berakhir September 2021. Turunkan perannya jadi
sumber riwayat saja.

**3. Tahap 4 — Pasca laga.** Nol dari tujuh, dan datanya sudah diam (laga
selesai), jadi paling mudah diuji. Handoff menaruhnya sebelum Live justru
karena itu.
