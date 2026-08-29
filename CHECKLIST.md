# Checklist Implementasi — MU Analytics

Status tiap butir design handoff terhadap kode yang benar-benar ada.
Diaudit **24 Agustus 2026** dengan membaca file, bukan menebak dari nama.
Diperbarui **29 Agustus 2026** sesudah SQ-01, SQ-02, dan seluruh Tahap 4.

Keterangan status: **✅ selesai** · **🟡 sebagian** · **⬜ belum** · **🚫 terblokir**

> Angka di sini dari **produksi**, bukan DB lokal. Sumber keputusan & jebakan
> ada di [CATATAN-PERUBAHAN-BESAR.md](CATATAN-PERUBAHAN-BESAR.md).

---

## Ringkasan

| Tahap | ✅ | 🟡 | ⬜ | 🚫 | Keadaan |
|---|--:|--:|--:|--:|---|
| 0 — Fondasi data | 9 | 6 | 3 | 0 | Ketersediaan akhirnya punya skorsing, pinjaman, dan Bentrok |
| 1 — Penarikan & rekonsiliasi | 10 | 5 | 0 | 0 | **Konflik dua feed nyata, pilihan analis tersimpan** |
| 2 — Halaman rujukan | 14 | 3 | 1 | 2 | **Skuad selesai** — SQ-01 + SQ-02 |
| 3 — Metrik turunan | 1 | 1 | 4 | 1 | LV-08 beban 14 hari, dirujuk 3 kartu |
| 4 — Pasca laga | 6 | 1 | 0 | 0 | **Seluruh halaman jadi** — PS-01…PS-05 + Laporan |
| 5 — Pra laga | 5 | 1 | 5 | 0 | Halaman Pra-laga hidup — PR-01/02/03/04/05 |
| 6 — Live | 0 | 3 | 9 | 0 | Belum dimulai |
| Lintas halaman | 3 | 5 | 3 | 0 | Helper konvensi skor lahir, baru dipakai satu halaman |

**324 test lulus.** Sembilan halaman hidup: `/`, `/jadwal/`, `/pra/`, `/pasca/`,
`/skuad/`, `/statistik/`, `/berita/`, `/cedera/`, `/match/<id>/`.

> Angka Tahap 1 sebelumnya salah hitung (tertulis 7/4/1/1 untuk 15 baris).
> Sudah dihitung ulang.

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
| ✅ | `Injury/Availability` | Skorsing, pinjaman, beban menit, dan status `Bentrok` semuanya ada. `Injury` tetap RIWAYAT, `PlayerAvailability` KEADAAN SEKARANG |
| ✅ | `SourceHealth` | `matches/source_health.py` dipanggil context processor, tampil di semua halaman |
| 🟡 | Tabel `source` | Cuma enum `DataSource`; ambang kesegaran ter-hardcode |
| 🟡 | Tabel `ingest_log` | `MatchIngest` itu keadaan terakhir, bukan log. `rows` kini omong kosong |
| 🟡 | Syarat selesai B: tidak ada nama ganda | **60 kunci nama aktif masih muncul >1×** (mayoritas orang berbeda) |
| ⬜ | `PlayerSeasonStats` (per kompetisi per musim) | Diagregasi on-the-fly; tanpa ini tidak ada dasar pembanding se-liga |
| ⬜ | `TransferRumour` | App `transfers/` masih stub Django |
| ✅ | `NewsItem` | App `news/`, 9 feed, ~90 berita tersimpan |
| ✅ | `PlayerAvailability` | Status per-sumber, dua penulis: FPL dan turunan judul berita |
| ✅ | `SavedMoment` | `matches/models.py` — asal analis vs asal sistem dibedakan |
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
| ✅ | Halaman Skuad menampilkan konflik | Panel SQ-01, dua kotak berdampingan + umur data |
| ✅ | Pilihan analis tersimpan | `AvailabilityDecision` — statusnya ikut disalin, bukan cuma sumbernya |
| ✅ | Konflik ketersediaan dari dua feed | FPL + turunan judul berita. **Kriteria selesai Tahap 1 terpenuhi** |

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

### Skuad — ✅ selesai
| | Butir | Catatan |
|---|---|---|
| ✅ | Rangka tabel 6 kolom sesuai desain | Pemain · Pos · Status · Catatan · Perkiraan kembali · Beban 14 hr |
| ✅ | Pill status | Bugar hijau · Diragukan kuning · Absen merah · Dipinjamkan biru · **Bentrok ungu** |
| ✅ | Kolom Beban 14 hr + pewarnaan risiko | Ambang yang sama dengan LV-08 |
| ✅ | Header: waktu pembaruan + jumlah sumber | |
| ✅ | **Panel Konflik Sumber (SQ-01)** | Dua kotak berdampingan, umur data masing-masing, tombol pilih & batalkan. **Ketiga aturannya ditulis di UI**, bukan cuma di dokumen |
| ✅ | Urutan prioritas sumber ketersediaan | `players/availability.py`. FPL di atas NEWS — penyimpangan dari handoff yang ditulis alasannya |
| 🟡 | Perkiraan kembali | Cuma diisi kalau sumbernya menyebut tanggal. Desain minta median durasi cedera sejenis; riwayat kita belum cukup, dan tebakan di kolom "perkiraan" lebih berbahaya daripada kolom kosong |

### Berita — ✅ hidup
| | Butir | Catatan |
|---|---|---|
| ✅ | Halaman + route `/berita/` | 9 feed, semuanya diuji hidup |
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

## Tahap 4 — Pasca laga — ✅ hidup di `/pasca/`

| | Butir | Catatan |
|---|---|---|
| ✅ | **Pemilih Laga (PS-01)** | 12 chip; laga lama di luar chip tetap bisa dibuka lewat URL |
| ✅ | **Laporan Pertandingan** | Dua paragraf otomatis. `Susun ulang` mengganti susunan kalimat, **angkanya tidak pernah berubah** — ada tesnya |
| ✅ | **Angka Penentu (PS-02)** | Empat metrik paling menyimpang dari kebiasaan musim, diukur simpangan baku. **Menolak menjawab** di bawah 6 laga pembanding |
| ✅ | **Nilai Pemain (PS-03)** | `matches/ratings.py`, bobot per posisi. Baris tanpa data → `None`, bukan 6,0. Cadangan tak turun → "tidak turun" |
| 🟡 | **Saved Moments (PS-04)** | Detektor sistem jalan; varian "asal live" belum bisa karena halaman Live belum ada |
| ✅ | **Generator Prompt (PS-05)** | Lima tipe konten, tiga pilihan sumber, tiga nada caption. Urutan blok dijaga tes |
| ✅ | Kriteria selesai handoff | Laporan laga lama dihasilkan tanpa campur tangan manual — dibuktikan `HalamanPascaTests` |

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
| 🟡 | Konvensi skor: MU selalu ditulis lebih dulu | `matches/scoreline.py` lahir dan bertes, tapi baru dipakai halaman Pasca. Halaman lain masih punya logikanya sendiri |
| ⬜ | Indikator kekuatan bukti (3/3 · 2/3) | Prinsip desain no. 4 |
| ⬜ | Toggle tampil/sembunyi chip sumber | |
| ⬜ | Prinsip "tanpa aset" | |

---

## Yang direkomendasikan berikutnya

**1. Tahap 3 — metrik turunan.** PPDA per laga tidak ada yang memblokir, dan
Nilai Pemain (PS-03) sudah menetapkan bobot per aksi yang selama ini jadi
alasan LV-06/PS-03 tertahan. Ini juga yang membuka Pemain Kunci (PR-06) dan
Profil Lawan (PR-07) di halaman Pra.

**2. Bursa transfer (Tahap belum bernomor).** `transfers/` masih stub, dan
Indeks Kebutuhan Skuad (BR-01) butuh bahan yang sekarang sudah ada semua:
menit per posisi, usia, dan output per 90.

**3. Tahap 6 — Live, mode putar ulang dulu.** Handoff tegas soal urutannya.
`RawPayload` sudah ada sebagai bahan tapi **belum ada satu pun pembacanya**.

**Utang yang masih berdiri:**
- Aturan 4 SQ-01 (susunan resmi menimpa semuanya) bertes tapi jarang menyala:
  penarik kita baru mendapat susunan pada atau sesudah kick-off.
- **Recall detektor berita rendah.** Di 484 berita produksi (10 hari) hasilnya
  0 temuan sah — semua penolakannya benar, tapi genre judul yang dominan itu
  rangkuman ("Amad, Mount, Baleba — injury news and return dates"), bukan klaim
  per pemain. Panel Konflik Sumber akan sering kosong sampai ada judul yang
  jelas menyebut satu pemain.
- 'Tyrell Malacia' (lokal) punya dua record dan `merge_duplicates` sengaja
  melewatinya — salah satunya bertim "No Club" sehingga aturan pengaman "main
  di tanggal sama untuk klub berbeda" kena palsu. Butuh mata manusia.
- Sebagian besar pemain lawan `position`-nya kosong. Mereka dinilai pakai
  bobot TENGAH, dan itu membatasi seberapa jauh `calibrate_ratings` bisa
  dipercaya (134 dari 377 baris yang bisa dipakai).

**Sudah lunas:**
- **Produksi sudah jalan** — 9 halaman 200, dua migrasi terpasang, backup
  terverifikasi diambil sebelum migrate.
- **Cron `derive_availability_news`** tiap jam :45 (17 job sekarang).
- Bobot nilai pemain **sudah diukur** terhadap rating FotMob (r = 0,850,
  sebaran 0,76 vs 0,74) dan sengaja tidak diubah — uji silangnya menolak.
  `python manage.py calibrate_ratings --cari` mengulang pemeriksaannya.
- `matches/scoreline.py` dipakai `match_result` dan Dashboard, bukan cuma Pasca.
- Duplikat pemain produksi digabung: 3169 → 3167 record, **statistik tetap
  27.887** (tidak ada yang hilang), skuad MU tetap 38.
- `deploy-exclude.txt` — perintah rsync di README ternyata bakal menghapus
  `.htaccess`, `scripts/backup-db.sh`, dan seluruh `backups/`.
