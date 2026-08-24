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
| 0 — Fondasi data | 8 | 7 | 3 | 0 | **NewsItem & PlayerAvailability** akhirnya ada |
| 1 — Penarikan & rekonsiliasi | 7 | 4 | 1 | 1 | **Chip sumber & Kesehatan Sumber akhirnya tampil** |
| 2 — Halaman rujukan | 12 | 7 | 2 | 2 | Statistik & **Berita** jadi; Skuad separuh |
| 3 — Metrik turunan | 1 | 1 | 4 | 1 | **LV-08 beban 14 hari jadi**, dirujuk 3 kartu |
| 4 — Pasca laga | 0 | 0 | 7 | 0 | **Nol baris kode** |
| 5 — Pra laga | 5 | 1 | 5 | 0 | **Halaman Pra-laga hidup** — PR-01/02/03/04/05 |
| 6 — Live | 0 | 3 | 9 | 0 | Belum dimulai |
| Lintas halaman | 3 | 4 | 4 | 0 | Chip sumber, Kesehatan Sumber, Konflik tampil |

**240 test lulus.** Delapan halaman hidup: `/`, `/jadwal/`, `/pra/`, `/skuad/`, `/statistik/`, `/berita/`, `/cedera/`, `/match/<id>/`.

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
| ✅ | `NewsItem` | App `news/`, 8 feed, 86 berita tersimpan |
| ✅ | `PlayerAvailability` | Status per-sumber — fondasi panel Konflik Sumber |
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
| 🟡 | **Panel Konflik Sumber (SQ-01)** | **Tidak terblokir lagi** — FPL jadi sumber kedua, konfliknya nyata (Amad: FotMob bugar vs FPL 75%). Tinggal panelnya dibangun |
| 🟡 | Urutan prioritas sumber ketersediaan | Datanya sudah dua sumber; aturannya belum ditulis |

### Berita — ✅ hidup
| | Butir | Catatan |
|---|---|---|
| ✅ | Halaman + route `/berita/` | 8 feed, semuanya diuji hidup |
| ✅ | Umpan Berita bertingkat A/B/C | Aturan redaksi ditulis di UI, bukan cuma dokumen |
| ✅ | Kesehatan Sumber | Lewat context processor |
| 🟡 | "N sumber sepakat" | Dihitung per **grup kepemilikan** (Reach plc = 1), dan menandai kalau semua mengutip orang yang sama. Tapi pengelompokan topiknya masih kasar — nama depan kadang terpisah jadi topik sendiri ("Alejandro", "Lewis") |
| ⬜ | Sentimen Fans | Desain bilang **diisi manual**; app sengaja tidak mengarang angka dari judul |
| 🚫 | The Athletic & BBC | Larangan tertulis, bukan hambatan teknis. Ornstein jadi **tidak punya jalur sah** |

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

**1. Panel Konflik Sumber di Skuad (SQ-01).** Sekarang benar-benar bisa —
`PlayerAvailability` sudah berisi dua sumber, dan konfliknya nyata:
Amad Diallo dianggap bugar oleh FotMob tapi *"75% chance of playing"* oleh
FPL. Tinggal dua kotak berdampingan dengan umur data masing-masing.

**2. Tabel Ketersediaan (SQ-02).** Pill Bugar/Diragukan/Absen/Dipinjamkan
datanya sudah ada, dan kolom Beban 14 hr sudah jadi. Ini melengkapi halaman
Skuad versi desain.

**3. Tahap 4 — Pasca laga.** Nol dari tujuh, dan datanya sudah diam (laga
selesai), jadi paling mudah diuji. Handoff menaruhnya sebelum Live justru
karena itu.

**Utang yang lahir hari ini:**
- Pengelompokan topik di panel Kesepakatan masih kasar — nama depan terpisah
  jadi topik sendiri. Perlu penggabungan nama depan+belakang.
- `Injury` (Highlightly) sekarang cuma berguna sebagai **riwayat**, bukan
  status. Perannya di halaman Cedera perlu diperjelas.
