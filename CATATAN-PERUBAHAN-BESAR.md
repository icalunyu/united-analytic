# Catatan Perubahan Besar — Fondasi Data MU Analytics

Dokumen ini merekam satu rentetan kerja yang mengubah lapisan data proyek ini
dari "cukup untuk 5 halaman sederhana" jadi "siap membangun Meja Analisis
7 halaman" sesuai design handoff.

Ditulis supaya keputusan dan jebakannya tidak hilang. Banyak temuan di sini
hanya kelihatan sekali — kalau tidak dicatat, orang berikutnya (atau kita
sendiri tiga bulan lagi) akan menabraknya lagi.

Rentang: commit `43f7ed8` sampai `0b0ea9d`, 15 commit.
Semua angka diverifikasi langsung ke database produksi, bukan dari ingatan.

---

## 1. Ringkasan angka

| | Awal | Akhir |
|---|---|---|
| Match | 375 | **717** (342 tanpa MU) |
| Player | 481 | 1.370 |
| "Skuad MU aktif" | **294** (salah) | **38** (benar) |
| Statistik pemain per laga | 0 | **12.306** |
| Statistik tim per laga | 11 field | **40 field**, 776 baris |
| Tembakan ber-xG | 0 | **9.541** |
| Momentum per menit | 0 | 35.624 titik |
| Play-by-play berkoordinat | 0 | 3.171 |
| Baris statistik bernama ganda | 26 | **0** |
| Jejak sumber per angka | tidak ada | **96%** |
| Database | SQLite 15 MB | **Postgres 38 MB** |
| Test | 0 | **61** |
| Sumber data aktif | 6 | 8 |

---

## 2. Tiga keputusan penentu lingkup

Design handoff menuntut hal-hal yang tidak semuanya bisa dipenuhi data gratis.
Tiga keputusan ini menentukan bentuk produk, dan ketiganya sudah dijawab.

### Keputusan 01 — Kartu Lapangan kehilangan 3 dari 4 lapisan

**Masalah.** Desain minta empat lapisan: Jaringan umpan, Heatmap, Zona,
Tembakan. Tiga yang pertama butuh koordinat **setiap sentuhan**. Kita punya
72 event per laga dengan koordinat hanya pada tembakan, pelanggaran, dan sepak
pojok. Feed penuh berisi 1.500–2.000 event.

**Diuji, bukan diasumsikan.** FBref (403), WhoScored (403), Sofascore (koneksi
ditolak di level TLS), StatsBomb Open Data (Premier League terbaru 2015/2016).
Diuji dari dua lokasi berbeda: sandbox dan server produksi. Tidak ada penyedia
gratis yang memberi event stream penuh untuk EPL musim berjalan.

**Keputusan: ganti dengan visual dari data yang ada.** Bentuk penggantinya
sudah dirancang dan diuji memakai data asli:

| Lapisan asli | Jadi |
|---|---|
| Tembakan | **Utuh**, malah lebih kaya (xGOT + peta mulut gawang) |
| Jaringan umpan | **Tabel keterlibatan** — sengaja bukan di atas lapangan |
| Heatmap | **Peta kejadian**, 46 titik, kerapatannya dibiarkan terlihat jarang |
| Zona 6×3 | **Teritori** dua wilayah dari umpan per paruh |

**Catatan desain yang penting.** Tabel keterlibatan sengaja *tidak* digambar
di lapangan. Kita tahu berapa kali seorang pemain menyentuh bola, tapi tidak
tahu **di mana**. Menggambarnya di lapangan berarti mengarang posisi. Alasan
yang sama dipakai untuk menolak membuat heatmap dari 46 titik: hasilnya akan
terlihat padat dan meyakinkan padahal isinya hampir tidak ada.

### Keputusan 02 — Cakupan liga

**Masalah.** 375 laga di database, **nol** di antaranya tanpa MU. Enam card di
handoff butuh tolok ukur se-liga: Indeks Kebutuhan Skuad (persentil 60 liga),
Pemain Kunci (z-score per posisi), Profil Lawan (bar persentil), Fakta
Pendukung ("3 teratas/terbawah liga"), Hipotesis Taktik, Spesifikasi Profil.

**Koreksi perhitungan saya sendiri.** Awalnya saya menaksir opsi ini butuh
**760 panggilan API per hari** dan menjadikannya alasan utama menahan. Itu
salah — saya memproyeksikan perilaku boros command yang ada (menarik ulang
semua laga selesai tiap malam) ke skala 10×. Laga yang sudah selesai datanya
final. Angka sebenarnya setelah ingestion dibuat inkremental: **~4 panggilan
per hari**, lebih ringan dari sebelumnya. Dugaan saya 197× kelewat tinggi.

**Keputusan: tarik seluruh liga.** Backfill 380 laga Premier League 2025/26.

**Kekhawatiran yang tidak terbukti.** Saya memperingatkan duplikat akan naik
10×. Hasilnya: pemain hanya naik 11% (1.254 → 1.390), tim tidak bertambah sama
sekali, dan `merge_duplicates` menemukan **nol** duplikat baru. Sebabnya
FotMob mengirim ID pemain sendiri, jadi pencocokan nama — sumber duplikat
sebelumnya — praktis tidak pernah jalan di jalur ini.

### Keputusan 03 — Jejak sumber per angka

**Masalah, dan lebih besar dari sekadar metadata.** Prinsip kedua handoff:
setiap angka membawa sumbernya. Selain tidak ada jejaknya, ternyata provider
**saling menimpa diam-diam**: 5.678 baris punya `xg` (Understat) sekaligus
`rating` (FotMob), dan nilai `xg` yang tersimpan tergantung cron mana yang
jalan terakhir malam itu.

Field yang diperebutkan: 13 antara FotMob dan ESPN, 3 antara FotMob dan
Understat.

**Keputusan: bangun sekarang, sebelum ada halaman yang membacanya.**
`field_sources` (JSONB) + `players/provenance.py`.

**Prioritas yang dipilih.** Default FotMob > Understat > ESPN berdasar
kelengkapan. Satu pengecualian disengaja: **semua turunan xG** (`xg`, `xa`,
`xg_chain`, `xg_buildup`, `key_passes`, `minutes_played`) dipegang Understat,
supaya angka-angka itu datang dari satu model yang sama dan konsisten satu
sama lain.

**Konsekuensi yang sengaja dibiarkan.** xG pemain dari Understat, xG tim dari
FotMob — total tim **tidak akan persis sama** dengan jumlah xG pemainnya. Itu
sifat menggabung provider, bukan bug. Bedanya sekarang ketidakcocokan itu
kelihatan lewat `field_sources`, bukan tersembunyi.

---

## 3. Sumber data

### Yang ditambahkan

**FotMob** (`pull_fotmob`) — penambahan data terbesar yang tersedia gratis.
Endpoint `api/data/matchDetails`, tanpa API key, cukup header `Referer`.

Yang hanya ada di sini:
- **Aksi bertahan per pemain** (tackles, interceptions, recoveries, dribbled
  past, blocks, clearances). ESPN tidak punya satu pun.
- **Umpan dipisah paruh sendiri vs paruh lawan** → membuat PPDA bisa dihitung.
- **xGOT** (kualitas eksekusi, beda dari xG yang kualitas peluang) + titik
  lintasan bola di mulut gawang.
- **Kurva momentum per menit**, skala −100..100.
- **Koordinat slot formasi** ternormalisasi 0–1.

**Understat** (`pull_xg_understat`) — xG level tembakan + xA/xGChain/xGBuildup
dan menit bermain per pemain.

> **Jebakan:** struktur lama (`datesData`, `shotsData` tertanam di HTML) yang
> dipakai hampir semua tutorial scraping **sudah dihapus**. Datanya pindah ke
> endpoint JSON `getTeamData/` dan `getMatchData/`, dan satu-satunya syarat
> akses adalah header `X-Requested-With: XMLHttpRequest`. Tanpa itu server
> membalas **404**, bukan 403 — jadi kalau suatu hari command ini mendadak 404
> semua, tersangka pertamanya syarat header, bukan match-nya yang tidak ada.

### Yang diuji dan ditolak

| Sumber | Sandbox | Server produksi | Catatan |
|---|---|---|---|
| FBref | 403 | 403 | anti-scraping, konsisten |
| WhoScored | 403 | 403 | Incapsula |
| Sofascore | koneksi ditolak | — | diblokir di level TLS |
| StatsBomb Open Data | 200 | — | Premier League terbaru **2015/2016** |

StatsBomb tetap berguna, bukan untuk data MU tapi untuk **membangun dan
menguji model** — kalau nanti bikin grid xT sendiri, datanya lengkap dan gratis
di situ.

### ESPN — dipakai jauh lebih dalam

Sebelumnya `pull_match_events_espn` membuang sebagian besar payload yang sudah
diunduh. Sekali jalan sekarang menyimpan:

- **Event** (gol/kartu/substitusi) → `MatchEvent`, untuk timeline
- **Seluruh play-by-play** berikut koordinat lapangan → `MatchPlay`
- **28 statistik tim** (dari 11)
- **Statistik per pemain per laga** + formasi awal
- **Payload mentah** → `RawPayload`

---

## 4. Bug yang ditemukan

Delapan bug, semuanya ditemukan sambil mengerjakan hal lain — dan semuanya
diam.

### 4.1 ESPN mengirim play duplikat
96 entri `commentary` hanya berisi **60 `play.id` unik**. Dedup awal memakai
`sequence` (yang memang unik per entri), sehingga duplikatnya lolos dan
menggelembungkan momentum **22%**. Kunci dedup harus `play.id`.

### 4.2 `_team_by_name` salah atribusi
Fallback-nya mengembalikan `home_team` kapan pun nama tidak cocok persis. Jadi
event tim tamu dengan varian nama (`"Brighton and Hove Albion"` vs
`"Brighton & Hove Albion"`) tercatat ke tuan rumah. Sekarang memakai matcher
dedup yang sama dan mengembalikan `None` kalau ragu.

### 4.3 `field_x = 0.0` bukan koordinat
Itu penanda "tidak ada data" untuk kartu dan substitusi. Kalau dianggap
koordinat asli, kartu terbaca sebagai kejadian tepat di mulut gawang.

### 4.4 Diakritik tidak dilipat di pencocokan nama
`Šeško` ≠ `Sesko`, `Bayındır` ≠ `Bayindir`, `Vítek` ≠ `Vitek`. Provider yang
menulis beraksen (Highlightly) membuat record baru alih-alih mencocok.

> Bug ini **menyembunyikan dirinya sendiri**: deteksi duplikat yang memakai
> kunci yang sama melaporkan **nol** duplikat. Baru setelah diakritiknya
> dilipat terpisah, ketahuan ada 3 pasang di lokal saja.

Sisi tim lebih parah lagi: `_NON_ALNUM_PATTERN` mengubah karakter non-ASCII
jadi **spasi**, jadi `Beşiktaş` bukan cuma beda ejaan tapi tercabik jadi
`'be ikta'`.

NFKD saja tidak cukup — `ı` (dotless i Turki), `ø`, `đ`, `ł` tidak punya
dekomposisi dan butuh peta manual.

### 4.5 Parser tinggi badan menggabungkan semua digit
`"179 cm (5 ft 10 in)"` → `179` + `5` + `10` = **`179510`**. SQLite menerimanya
diam-diam karena tidak menegakkan batas kolom; Postgres langsung menolak
(`smallint out of range`) saat migrasi.

**Ini alasan konkret kenapa pindah ke Postgres itu benar:** data rusak yang
tersembunyi berbulan-bulan jadi kelihatan.

### 4.6 `is_active` tidak pernah disetel
Defaultnya `True` dan tidak ada satu pun command yang pernah mengubahnya. Jadi
setiap pemain yang pernah tercatat di MU terhitung "Skuad Aktif" selamanya —
termasuk yang pindah bertahun-tahun lalu dan hanya terbawa dari data historis
Premier League.

### 4.7 ESPN tidak mencatat ingest
Kartu Kesehatan Sumber menampilkan ESPN **"berhenti"** padahal justru dia yang
paling sering jalan (tiap 10 menit). Dibiarkan, indikator itu akan terus
memberi alarm palsu untuk feed paling sehat, dan analis berhenti
mempercayainya.

### 4.8 `formation_place` bukan urutan per baris
Di 4-2-3-1 milik MU, urutan slot untuk susunan sebenarnya adalah
**1, 3, 6, 5, 2, 8, 4, 11, 10, 7, 9**. Slot 4 itu Mainoo (gelandang),
sementara slot 5 dan 6 adalah Maguire dan Martínez (bek tengah). Memetakan
slot 2–5 sebagai bek empat menghasilkan formasi yang salah di layar **tanpa
ada yang sadar**. Untuk menggambar formasi, pakai `formation_x`/`formation_y`
dari FotMob.

### 4.9 Understat terkunci di musim yang sudah selesai
Ditemukan 2026-08-23, lima hari setelah sesi besar, saat memeriksa kesehatan
produksi. `UNDERSTAT_DEFAULT_SEASON` dipatok `'2025'` di `settings.py`. Musim
2025/26 tamat 24 Mei 2026 dan seluruh 38 laganya sudah tertarik, jadi penyaring
inkremental melewati semuanya. Hasilnya tiap malam:

```
38 match dilewati (sudah pernah ditarik, pakai --refresh buat paksa).
Selesai. 0 match dicocokkan, 0 tembakan, 0 statistik pemain disimpan.
```

**Exit code 0. Tidak ada error. Tidak ada baris di log yang terlihat merah.**
Padahal musim 2026/27 sudah berjalan dan tidak satu pun laganya dapat xG.
Understat adalah satu-satunya sumber xG/xA/xGChain/xGBuildup gratis yang
mencakup Premier League, jadi diamnya dia melumpuhkan seluruh lapisan xG untuk
musim berjalan.

Pelajaran yang lebih luas: **konstanta musim yang ditulis tangan adalah bom
waktu tahunan**, dan gejalanya bukan crash melainkan sukses palsu. Perintah
yang melapor "selesai" sambil menyimpan nol baris harus dicurigai.

Perbaikannya, `_current_football_season()` di `settings.py` menurunkan musim
dari tanggal hari ini — bulan >= 7 berarti musim tahun itu, sebelumnya musim
tahun lalu (batasnya diuji di 30 Juni vs 1 Juli). Variabel lingkungannya
dipertahankan sebagai override untuk backfill musim lama, tapi sekarang
dikosongkan secara default.

Catatan pemantauan: karena `MatchIngest.ingested_at` itu `auto_now` dan cuma
tersentuh kalau ada laga yang benar-benar masuk, sumber yang tidak menemukan
apa-apa akan terlihat makin tua di Kartu Kesehatan Sumber. Understat terbaca
**121 jam** — itulah petunjuk yang membongkar bug ini. Umur yang menua padahal
cron-nya sukses tiap malam justru sinyal, bukan derau.

---

## 5. Krisis kualitas data: 294 → 38

Setelah deploy, halaman Skuad menampilkan **294 pemain "MU aktif"**. Angka
sebenarnya 58. Ini terlihat langsung oleh pengguna.

Diagnosisnya dilakukan dengan reproduksi lokal, bukan tebakan:

| Command | Efek ke jumlah skuad |
|---|---|
| `pull_match_events_espn` (8 kompetisi) | 58 → 62 (+4) |
| `pull_squad`, `pull_squad_sdb` | tidak berubah |
| `pull_match_events_pl`, `pull_injuries` | tidak berubah |
| **`pull_match_events` (Highlightly)** | **62 → 83 dalam satu run** |

Pembersihannya berlapis:

1. **`fold_accents`** — menghentikan pembentukan duplikat baru (bug 4.4)
2. **`merge_duplicates`** — menggabungkan 3 tim + 32 pemain duplikat
3. **`clean_commentary_players`** — 243 baris sampah parser regex lama;
   177 di antaranya pemain klub lain, sisanya potongan kalimat commentary
   seperti `'Bruno Fernandes with a cross following a corner'`
4. **`is_active` di `pull_squad`** — 65 mantan pemain ditandai non-aktif
5. **Penggabungan co-occurrence** — 15 pasangan terakhir (bagian 6)

**Prinsip yang dipegang di semua alat pembersih:** default *dry run*, harus
`--apply` untuk menulis. Referensi FK di-enumerate **dinamis** dari `_meta`,
bukan di-hardcode — mayoritas FK ke `Team` itu `CASCADE`, jadi satu referensi
terlewat berarti `Match` ikut terhapus diam-diam.

---

## 6. Duplikat terakhir: satu orang, dua record

26 baris statistik bernama ganda ternyata **bukan kasus ambigu**:

```
Antoine Semenyo — laga sama, tim sama, 90 menit
  id=445   sumber=[espn, espn_commentary, premier_league, understat]
  id=1526  sumber=[fotmob]
```

Satu record memegang xG, satunya memegang sentuhan.

**Kenapa `merge_duplicates` melewatkannya:** ia mengelompokkan per
`Player.team`, dan ke-30 record ini punya `Player.team` **berbeda** — tiap
record terakhir disentuh provider berbeda yang menyebut klub berbeda. Beberapa
bahkan sisa bug 4.2 (Josh Cullen dan James Hill ter-set
`Player.team = Manchester United` padahal bukan pemain MU).

**Bukti identitas yang dipakai jalur baru:** muncul di **laga dan tim yang
sama**. Dua orang berbeda tidak mungkin dua-duanya bermain di satu laga untuk
satu tim dengan nama sama.

> **Bagian yang paling mudah salah:** isi kedua baris statistik harus
> **disatukan dulu** sebelum row-nya dibuang. Tanpa itu `absorb()` menghapus
> baris yang bentrok unique `(match, player)` — dan separuh datanya ikut
> hilang. Justru di situ masalahnya: satu punya xG, satunya punya sentuhan.

**Efek samping:** setelah duplikat digabung, `clean_commentary_players` bisa
menyelesaikan **5 kasus yang sebelumnya ambigu** — ambiguitasnya hilang karena
kandidat gandanya sudah menyatu. Ekor ambigu turun 15 → 10.

---

## 7. Migrasi ke Postgres

**Temuan:** produksi jalan di SQLite, padahal kredensial Postgres sudah
lengkap di `.env` dan driver `psycopg` terpasang.

**Dua penyebab, keduanya menjebak:**

1. **`DB_ENGINE` kosong.** `settings.py` memakainya sebagai saklar dengan
   SQLite sebagai fallback — jadi Django jatuh ke SQLite **tanpa error, tanpa
   warning**. Kelihatan jalan padahal Postgres tidak tersentuh.

2. **cPanel menambahkan awalan nama akun** ke database **dan** user, serta
   membuang tanda hubung. Yang di `.env` tertulis `mu-analytics` / `ical`,
   aslinya `musafarw_muanalytics` / `musafarw_ical`.

> **Koreksi diagnosis sebelumnya.** Sesi Claude lain menyimpulkan ini bug
> konfigurasi server dan menyarankan menghubungi support DomaiNesia. Itu tidak
> didukung bukti. Postgres membalas `no pg_hba.conf entry` **justru karena**
> user dan database yang diminta tidak ada. Begitu diuji dengan nama asli,
> errornya berubah jadi `password authentication failed` — artinya koneksi
> lolos tahap `pg_hba` dan konfigurasi server baik-baik saja. Diuji lewat tiga
> jalur (TCP `127.0.0.1`, `localhost`, Unix socket), semuanya sampai ke tahap
> password. **Tiket ke support tidak diperlukan.**

**Cara memastikan nama aslinya:** `uapi Postgresql list_databases`.

**Hasil migrasi:** 15.370 objek, **12 model cocok jumlahnya**, 17 sequence
diperiksa dan semuanya aman (kalau tidak, insert cron berikutnya bentrok
duplicate key).

**Catatan `DB_HOST`:** dikosongkan = lewat Unix socket. Default `'localhost'`
di `settings.py` **hanya** berlaku kalau variabelnya tidak ada sama sekali,
bukan kalau ada tapi kosong.

---

## 8. Operasional

### Cron

Jam server **WIB (UTC+7)**, bukan UTC. Laga MU jatuh 18:00–06:00 WIB — larut
malam di sini. Kalau dijadwalkan dengan asumsi UTC, polling rapat justru jatuh
saat tidak ada pertandingan.

```
*/10 0-5,18-23   pull_match_events_espn    jendela laga
0    6-17        pull_match_events_espn    di luar itu
0    */3         pull_fixtures_fd
03:50            rotate-logs.sh
04:00            pull_squad_sdb
04:05            pull_injuries
04:10            pull_match_events_pl
04:15            pull_squad
04:20            pull_xg_understat
04:25            pull_fotmob               kompetisi MU (piala, Eropa)
04:35            pull_fotmob --league      380 laga PL
```

Beban turun dari ~288 run/hari jadi ~93.

> **Kegagalan senyap yang harus diingat.** Satu instalasi crontab terlihat
> sukses tapi entrinya **hilang** — file 50 baris diterima, yang tersimpan 43,
> persis blok yang baru ditambahkan, tanpa pesan error apa pun. Percobaan
> kedua dengan komentar ASCII satu baris berhasil. Akar penyebabnya belum
> dikonfirmasi. **Selalu verifikasi entri benar-benar ada setelah
> `crontab <file>`; jangan percaya pada tidak adanya error.**

> **Jebakan kedua:** `crontab -l` di cPanel ini mencetak baris
> `Backup of musafarw's previous crontab saved to ...` ke **stdout**. Setiap
> siklus baca–edit–tulis akan menanamkannya kembali ke dalam crontab. Saring
> baris itu sebelum menulis ulang.

### Rotasi log

`logrotate` tidak tersedia untuk user di hosting ini (tidak ada di PATH maupun
`/usr/sbin`). Diganti [`scripts/rotate-logs.sh`](scripts/rotate-logs.sh),
harian 03:50, simpan 3 arsip `.gz`, rotasi hanya kalau > 1 MB.

> Log **disalin lalu dikosongkan di tempat**, bukan di-`mv`. Job cron yang
> kebetulan sedang jalan masih memegang file descriptor ke inode itu — kalau
> filenya dipindah, output-nya nyasar ke arsip dan hilang dari log aktif.

### Deploy

Server **bukan git repo** — deploy dilakukan dengan mengunggah file.
Konsekuensinya: tidak ada `git status` yang bisa memberi tahu kalau ada
penyimpangan; ketahuannya hanya lewat pembandingan checksum manual.

Catatan ini sempat ditulis di sini tapi README-nya dibiarkan tetap menyuruh
`git pull origin main`, dan pada 2026-08-23 jebakannya menggigit persis seperti
yang diperingatkan. Yang bikin mahal bukan `git pull`-nya gagal, tapi **cara
gagalnya**: perintahnya dipipe (`git pull origin main 2>&1 | tail -3`), dan
exit status sebuah pipeline itu milik perintah terakhir — `tail`, yang selalu
sukses. Jadi `set -e` tidak menggigit, `migrate` dan `collectstatic` di
belakangnya jalan normal, dan seluruh deploy melaporkan sukses padahal tidak
satu byte pun kode berubah. Ketahuan cuma karena nilai yang diperiksa sesudahnya
masih yang lama.

Dua pelajarannya: (1) dokumentasi yang salah lebih berbahaya daripada tidak ada
dokumentasi — README sekarang sudah diperbaiki dan memuat perintah `rsync` yang
sebenarnya dipakai; (2) **selalu verifikasi kode di server benar-benar berubah**
sesudah deploy, jangan percaya laporan sukses. Kalau memipe perintah yang
kegagalannya penting, pakai `set -o pipefail`.

Layout di server diratakan: `~/mu-analytics/players/`, bukan
`~/mu-analytics/backend/players/`.

Autentikasi memakai SSH key `portoical_deploy` yang sudah diotorisasi di host
itu. Password plaintext di `how-to-deploy.md` tidak dipakai dan layak dirotasi
(file itu ter-gitignore dan **tidak pernah** masuk history git — sudah dicek).

---

## 9. Model momentum

Dihitung sendiri di [`matches/momentum.py`](backend/matches/momentum.py) dari
play-by-play ESPN. Tiap kejadian dibobot menurut bahayanya, dikali kedekatan
ke gawang dari koordinat lapangan, lalu disebar ke menit sekitarnya. Nilainya
bertanda: positif tuan rumah, negatif tamu.

**Semantik `field_x` yang perlu diingat:** itu **jarak ke gawang yang
diserang** (0 = di garis gawang). Diverifikasi dari data: gol rata-rata 0,08–0,23
sementara pelanggaran 0,62. Dan `team` pada play `foul` adalah tim
**pelanggar**, jadi tekanan dikreditkan ke lawannya.

**Kalibrasi.** `calibrate_momentum` awalnya menembak Sofascore dan tidak
pernah bisa diuji karena endpoint mereka menolak koneksi dari mana pun.
Dialihkan ke FotMob, yang memberi data berbentuk sama dan bisa dijangkau.
Sekarang membaca dari database, jadi tidak menyentuh jaringan.

Patokan sekarang: korelasi rata-rata **+0,44** (Brighton +0,53, Forest +0,36).
Di bawah ambang 0,6 — masih ada ruang setel di `PLAY_WEIGHTS`, bedanya
sekarang hasil setelan itu **terukur**.

FotMob tidak memberi momentum untuk laga persahabatan (`momentum: false`),
jadi model sendiri tetap yang dipakai untuk tampilan karena jalan di semua
laga.

---

## 10. Jebakan parsing yang berulang

Tiga kali pola yang sama muncul dan layak diwaspadai:

1. **Tinggi badan** — semua digit digabung: `179510` (bug 4.5)
2. **Statistik FotMob** — nilai campur tipe dalam satu payload: angka polos
   (`13`), string desimal (`'0.79'`), dan berpersentase (`'415 (86%)'`). Yang
   terakhir kalau dibaca mentah jadi `41586`.
3. **Menit momentum FotMob** — **pecahan** untuk injury time (`90.25`, `90.5`,
   `90.75`). Disimpan sebagai integer, ketiganya membulat jadi 90 dan
   bertabrakan di unique constraint.

Ketiganya sekarang punya test regresi.

---

## 11. Pendeteksi konflik: butuh dua penyaringan

Percobaan pertama menghasilkan **51 konflik dalam satu laga**. Tidak ada analis
yang akan membaca itu.

**Penyaringan 1 — field hasil model.** Mayoritas konflik adalah xG dan xA:
`0.80 (Understat) vs 0.35 (FotMob)`. Itu **dua model berbeda mengukur hal yang
sama**, selalu selisih, selamanya. Bukan data rusak. → `MODELLED_FIELDS`

**Penyaringan 2 — selisih sistematis.** Sisa 20 semuanya `minutes_played`,
selisih 3–4 menit. Diukur: **13 pemain yang bermain 90 menit penuh sepakat
persis**, dan semua yang terlibat pergantian berselisih. Itu perbedaan jam
pertandingan antar provider, bukan kesalahan, dan tidak butuh keputusan
analis. → `FIELD_TOLERANCE`

Toleransi, bukan pengecualian total: selisih 40 menit tetap ditandai.

**Hasil 51 → 0** untuk laga itu, dan nol adalah jawaban yang benar.

> **Kartu Konflik Sumber di desain sebenarnya tentang status ketersediaan
> pemain**, bukan nilai statistik. Itu butuh **sumber cedera kedua** yang
> belum ada — sekarang hanya Highlightly, jadi tidak ada yang bisa berkonflik.

---

## 12. Batas yang diketahui

Tidak bisa dibangun dengan data gratis, **sudah diuji**:

- **Jaringan umpan, Heatmap, Zona 6×3** — butuh koordinat tiap sentuhan
- **xT per aksi** — butuh nilai posisi tiap aksi
- **Detektor tempo** — ambangnya "perubahan umpan per menit"; umpan hanya
  tersedia sebagai total per babak
- **Detektor pressing** — ambangnya PPDA jendela 15 menit. PPDA-nya sendiri
  bisa dihitung, tapi statistik tim FotMob hanya `All / FirstHalf / SecondHalf`
- **Posisi rata-rata pemain** — desain mendefinisikannya sebagai median semua
  aksi. FotMob memberi koordinat slot formasi, bukan posisi sebenarnya
- **Sebaran aksi di dialog Detail Pemain**

Satu-satunya data FotMob yang benar-benar per menit adalah kurva momentum.

**Sisa pekerjaan manual:** 10 kasus ambigu yang `clean_commentary_players`
menolak menebak (contoh: `Daniel James`, pernah di MU sekarang di Leeds, jadi
ada dua record asli). Menempelkan event ke orang yang salah lebih buruk
daripada menyisakannya. Tempatnya sudah ada di desain — kartu Konflik Sumber.

**424 baris tanpa jejak sumber** dari laga lama yang hanya dicover ESPN. Bukan
bug — kita memang tidak tahu asalnya karena ditulis sebelum sistem provenance
ada. Handoff punya aturannya: kalau tidak jelas asalnya, jangan ditampilkan.

---

## 13. Kesalahan saya di sesi ini

Dicatat supaya tidak terulang dan supaya konteksnya jujur.

**Klaim salah soal `.env` di git.** Saya menyebut `.env` dan `db.sqlite3`
ter-track git dan menyarankan rotasi API key. Salah — saya membacanya dari
listing filesystem, bukan index git. Keduanya ter-gitignore sejak awal dan
tidak pernah bocor.

**Alarm palsu soal file tertimpa.** Saya melaporkan telah menimpa
`prod.html`/`prod81.html` milik user. Setelah diperiksa lewat waktu pembuatan
inode: **saya sendiri yang membuat keduanya**. Sumber kekeliruan: blok "git
status di awal percakapan" di konteks saya ternyata bukan dari awal sungguhan.

**Perhitungan 760 panggilan/hari.** Salah 197×, dan sempat jadi alasan utama
menahan keputusan 02.

**Delapan proses latar tertinggal.** Tiap kali loop pemantau kena timeout, saya
membuat yang baru tanpa menghentikan yang lama — empat kali berturut-turut.
Yang tertua berjalan 1 jam 21 menit, polling SSH ke server tiap 20–30 detik
untuk pekerjaan yang sudah lama selesai. Seharusnya: satu perintah yang
berhenti sendiri, dan hentikan yang lama sebelum membuat pengganti.

**Penyaring inkremental salah tempat.** Awalnya saya taruh **sesudah**
panggilan API — tidak menghemat apa pun, karena yang mahal justru request-nya.

**Dua bug UI di mockup:** `.zone` diberi `position:absolute` sehingga keluar
dari grid dan menciut jadi 20px (angkanya benar dari awal, hanya tidak
terlihat), dan teks non-ASCII yang saya tulis langsung di JS rusak encoding-nya
— nama pemain aman karena `json.dumps` sudah meng-escape, string tulisan
tangan tidak.

**Commit yang menyapu folder tak terkait.** `git add -A` ikut memasukkan
`analytic-from-claude-design/` (4,5 MB) ke commit tentang parser tinggi badan.

---

## 14. Status per tahap design handoff

| Tahap | Status |
|---|---|
| 0 — Fondasi data | **7/7 selesai** |
| 1 — Penarikan & rekonsiliasi | **6/6 selesai** |
| 2 — Halaman rujukan (Skuad, Statistik, Berita) | 0/7 |
| 3 — Metrik turunan | 1/5 (momentum) |
| 4 — Pasca laga | 0/6 |
| 5 — Pra laga | 0/7 |
| 6 — Live | 0/9 |
| Lintas halaman | 0/5 |

**Belum ada satu halaman desain pun dibangun.** Semua kerja ini di lapisan
data — dan itu urutan yang benar menurut handoff.

### Yang direkomendasikan berikutnya

**Tahap 2, mulai dari Statistik.** Alasannya: datanya sudah lengkap dan tinggal
dibaca; model `PlayerSeasonStats` yang dibutuhkan **juga** merupakan tabel
tolok ukur untuk Indeks Kebutuhan Skuad, Pemain Kunci, dan Profil Lawan di
tahap berikutnya; dan kriteria selesainya tegas dari handoff — *"filter musim
dan kompetisi menghasilkan angka yang cocok dengan hitungan manual dari data
laga"*.

### Dua butir kritis yang mudah terlewat

- **`Hypothesis` dengan cap waktu pra-kickoff** (Tahap 5). Tanpa ini panel Cek
  Prediksi — yang handoff sebut pembeda utama produk — tidak punya dasar. Dan
  ini **tidak bisa ditambal belakangan**: prediksi yang tidak tersimpan sebelum
  kick-off hilang selamanya.
- **Mode putar ulang sebelum mode langsung** (Tahap 6). Handoff tegas soal ini.
  Prasyaratnya `RawPayload` sudah ada.

### Menggantung

- Understat `getLeagueData` — satu panggilan memberi 537 pemain se-liga dengan
  npxG dan xGChain. Melengkapi tolok ukur sisi serangan yang FotMob tidak punya.
- `pull_fixtures_fd` masih tiap 3 jam. Ia juga menyimpan skor dan status, jadi
  berfungsi sebagai cadangan kalau ESPN mati — sengaja tidak diturunkan lebih
  jauh.

---

## 15. Daftar commit

```
4153bd2  Siapkan deploy cPanel + fix guard nama pemain Highlightly
af9c018  Tambah momentum serangan, timeline match, & xG Understat
72cef81  Lipat aksen di pencocokan nama + command gabung duplikat
2b60e92  Command bersihin Player sampah bikinan parser commentary lama
c7c5679  Samain is_active sama skuad terkini di pull_squad
768a83f  Tambah rotasi cron.log
550ab00  Perbaiki parser tinggi badan + catat jebakan setup Postgres
91e8cf7  Integrasi FotMob: statistik pemain terlengkap, PPDA, momentum pembanding
1c13d63  Simpan koordinat slot formasi dari FotMob
d58d42f  Ingestion inkremental: jangan tarik ulang laga yang datanya sudah final
7c166af  Perluas ingestion FotMob ke seluruh Premier League
c56a70b  Jejak sumber per angka + prioritas provider yang deterministik
5cade4a  Gabungkan pemain yang muncul di laga & tim yang sama
85cfca6  Tahap 1: payload mentah, pendeteksi konflik, kesegaran feed
0b0ea9d  ESPN ikut mencatat ingest + payload mentah
```

## 16. Backup produksi

Tersimpan di `~/mu-analytics/` di server:

```
db.sqlite3.bak-*                 sebelum pembersihan & migrasi Postgres
backup-pg-20260817-113509.dump   sebelum integrasi FotMob
backup-pg-preliga-*.dump         sebelum backfill liga
backup-pg-preprov-*.dump         sebelum sistem jejak sumber
backup-pg-premerge-*.dump        sebelum penggabungan co-occurrence
backup-pg-premerge2-*.dump       sebelum penggabungan sisa roster (23 Agu)
backup-pg-prebackfill-*.dump     sebelum backfill ESPN 6 musim (23 Agu)
backup-pg-postbackfill-*.dump    sesudah backfill, sebelum merge lanjutan
```

Rollback ke SQLite kalau perlu: kosongkan `DB_ENGINE`, `touch tmp/restart.txt`.


---

## 17. Sesi 23 Agustus: tiga masalah operasional

Lima hari cron berjalan sendirian, lalu tiga masalah ketahuan sekaligus.
Yang menyatukan ketiganya: **tidak satu pun memunculkan error.** Semuanya
melaporkan sukses sambil diam-diam tidak bekerja.

### 17.1 Highlightly: quota dibakar mantan pemain

`pull_injuries` me-loop semua Player bertim MU — 98 orang, 60 di antaranya
mantan pemain. Mantan pemain tidak akan pernah lolos verifikasi klub (klub
mereka di Highlightly bukan MU lagi), jadi tiap malam mereka membakar 2+
panggilan hanya untuk gagal. Quota harian habis sebelum skuad inti sempat
diperbarui — 6 kali dalam 6 hari log.

Perbaikannya tiga lapis, dan urutannya penting:

1. Default hanya skuad aktif. 154 → 43 panggilan per malam.
2. Pemain yang sudah ter-link diproses **duluan**. Mereka cuma butuh 1
   panggilan dan justru merekalah yang datanya kepakai; kalau quota habis di
   tengah, yang kepotong pencarian pemain baru, bukan pembaruan cedera skuad
   inti.
3. `--max-calls` dan batas verifikasi kandidat per pemain. Nama umum bisa
   mengembalikan belasan kandidat yang semuanya lolos pencocokan nama.

Hasil nyata: 44/80 panggilan, tuntas, 259 entri cedera terproses.

### 17.2 Duplikat: metriknya sendiri menyesatkan

Angka "55 kunci nama pemain aktif muncul lebih dari sekali" yang saya pakai
sebagai alarm ternyata **sebagian besar bukan duplikat**. Kunci pengelompokan
adalah (inisial depan, nama belakang) — cukup untuk mencocokkan 'S. Amrabat'
dengan 'Sofyan Amrabat', tapi begitu dipakai melintasi seluruh liga ia
menyatukan orang yang jelas berbeda: *Aaron* vs *Alfie* Cresswell, *Abdou* vs
*Amad* vs *Amadou* Diallo, *André* vs *Angel* Gomes, *Adrian* vs *Andreas*
Pereira.

Pelajarannya: **sebuah metrik pemantauan bisa jadi sumber alarm palsu yang
justru menyita perhatian dari kerusakan yang nyata.** Yang benar-benar merusak
bukan jumlah nama kembar, melainkan berapa pemain yang statistiknya terbelah.

Dua kelas kerusakan nyata ditemukan, masing-masing butuh bukti berbeda:

**Sisa roster** (`_merge_roster_leftovers`). `pull_match_events_pl` membuat
Player untuk seluruh skuad Premier League. Waktu pemainnya pindah klub,
provider lain mencatatnya di klub baru, dan karena `resolve_player`
mencocokkan nama HANYA dalam satu tim, lahir record kedua. Yang lama tertinggal
tanpa statistik.

Waktu ditemukan, belum ada data yang rusak — statistiknya menumpuk di satu
record. Yang dicegah justru yang akan datang: selama dua record hidup,
`pull_match_events_pl` terus resolve lewat `premier_league` id ke record lama
sementara ESPN/FotMob ke record baru. Begitu pemainnya main lagi, terbelah.

**Transfer** (`_merge_transfers`). Di sini kerusakannya sudah terjadi: James
Ward-Prowse punya 12 laga di record West Ham dan 18 di record Burnley, jadi
tolok ukur se-liga membacanya sebagai dua pemain setengah-musim. 15 grup
serupa: Kudus West Ham → Tottenham, Zinchenko Arsenal → Forest, Nørgaard
Brentford → Arsenal.

Buktinya sederhana dan kuat: **tidak boleh ada satu tanggal pun yang muncul di
dua record.** Satu orang tidak bisa membela dua klub di hari yang sama.

### 17.3 Kanonik: "MU menang" hampir jadi bencana

Aturan pertama saya — kalau salah satu record ada di MU, dialah yang
dipertahankan — terdengar masuk akal: skuad MU satu-satunya roster yang
disegarkan tiap hari. Dry run membuktikannya berbahaya.

Parser komentar ESPN sempat salah-atribusi pemain lawan ke MU, menyisakan
record hantu: non-aktif, nol statistik, satu-satunya sumber `espn_commentary`.
Ademola Lookman, Calvert-Lewin, Daniel James, dan Jayden Bogle semuanya punya
record MU semacam itu **padahal tidak pernah membela MU**. Aturan naif
menjadikan hantu itu kanonik dan membuang record asli yang punya 20–37 laga.

Syaratnya diperketat jadi tiga: harus MU, harus `is_active`, dan harus punya
sumber selain komentar. Sesudah itu Jadon Sancho lolos dengan benar (record
MU-nya non-aktif karena sudah pindah, jadi yang menang Aston Villa dengan 23
laga) dan Karl Darlow juga (aktif di skuad MU lewat `football_data`, jadi dia
yang dipertahankan meski seluruh statistiknya dari masa Leeds).

**Ini alasan `--apply` tidak boleh jadi default.** Dry run yang dibaca baris
per baris adalah yang menangkapnya, bukan test.

### 17.4 Julukan klub

`team_names_match` sudah menangani nama pendek yang berupa awalan persis
('Brighton' vs 'Brighton & Hove Albion'), tapi 'Wolves' bukan awalan
'Wolverhampton Wanderers'. Akibatnya dua record Team untuk satu klub, dan 6
laga nyangkut di klub yang tidak punya satu pun pemain. Peta `_TEAM_ALIASES`
sengaja pendek dan hanya yang tidak ambigu — 'Sheffield' tidak masuk (United
atau Wednesday?).

### 17.5 Momentum: celahnya seluruhnya historis

Kurva momentum dihitung **live di view** dari `MatchPlay`, tidak pernah
disimpan. Tabel `MatchMomentum` isinya murni FotMob dan cuma dipakai
`calibrate_momentum` sebagai pembanding. Jadi kurva hanya muncul di laga yang
punya play-by-play ESPN — waktu diperiksa, 45 laga.

Sebarannya memberi tahu persis di mana celahnya: musim 2025 dan 2026 hampir
penuh, musim 2019–2024 **kosong sama sekali**. ESPN ternyata melayani musim
lama lewat parameter `season`, jadi backfill enam musim menutupnya:

| | sebelum | sesudah |
|---|---|---|
| `MatchPlay` | 3.246 | 31.073 |
| Laga MU punya momentum | 45 dari 325 | **421 dari 437** (96%) |
| Match | 722 | 823 |
| `PlayerMatchStatistics` | 12.500 | 27.777 |
| Player | 1.434 | 3.148 |
| Team | 60 | 89 |

Sisa 16 laga tanpa kurva itu laga yang ESPN memang tidak punya play-by-play-nya
(sebagian friendly dan cup lama), bukan kegagalan penarikan.

Fallback ke momentum FotMob sempat dipertimbangkan dan **ditolak berdasarkan
data**: hanya 1 laga MU yang punya FotMob tanpa play ESPN, jadi kerumitannya
tidak dibayar apa pun.

Dua efek samping yang wajib diantisipasi kalau backfill diulang:

1. **Skuad MU melonjak 38 → 79.** Record pemain historis lahir dengan
   `is_active` default. `pull_squad` adalah penyelarasnya — wajib dijalankan
   sesudah backfill, bukan opsional.
2. **Duplikat ikut lahir.** Backfill menambah 28 tim lawan dan ~1.500 pemain
   dari enam musim. Jalankan `merge_duplicates` sesudahnya.

Urutan yang benar: `pull_match_events_espn --season N` → `pull_squad` →
`merge_duplicates` (dry run, dibaca) → `merge_duplicates --apply`.

Skripnya ada di `scripts/backfill-espn.sh`. Sekali jalan, tidak masuk cron.

### 17.6 Deploy: `git pull` yang gagal tapi tampak sukses

Server **bukan git repo**, tapi README menyuruh `git pull origin main`.
Perintahnya dipipe (`git pull ... | tail -3`), dan exit status pipeline itu
milik perintah terakhir — `tail`, yang selalu sukses. Jadi `set -e` tidak
menggigit, `migrate` dan `collectstatic` jalan normal, dan deploy melapor
sukses padahal tidak satu byte pun berubah.

Ketahuan hanya karena nilai yang diperiksa sesudahnya masih yang lama.
README sudah diperbaiki dengan perintah `rsync` yang sebenarnya dipakai. Kalau
memipe perintah yang kegagalannya penting, pakai `set -o pipefail`.


---

## 18. Sesi 23 Agustus (lanjutan): Tahap 1.5 — pagar

Sesudah survei menyeluruh, tiga angka ternyata **tayang dan salah**, dua di
antaranya akibat kerja di sesi yang sama. Ditambah satu tenggat yang tidak bisa
ditunda.

### 18.1 Rekomendasi saya sendiri bertentangan dengan handoff

Saya sempat merekomendasikan `Hypothesis` dengan **penguncian**: tolak `save()`
kalau `now > kickoff_at`. Handoff melarangnya dengan kalimat yang tidak bisa
ditafsir dua arah:

> "Tidak ada mekanisme kunci atau approval. Framing yang sudah disepakati
> dengan user: 'sampai konten ini diunggah, beginilah prediksi kami' — prediksi
> terus diperbarui otomatis sampai kick-off, dan tiap konten membawa cap waktu
> versi yang dipakai. **Jangan menambahkan tombol lock, status 'diperiksa oleh
> X', atau approval flow; app tidak punya login sehingga klaim itu tidak bisa
> dibuktikan.**"

Pelajarannya: **baca spesifikasi sebelum merekomendasikan bentuk, bukan
sesudah.** Rekomendasi itu keluar dari penalaran "prediksi harus bisa
dibuktikan pra-laga, jadi harus dikunci" — masuk akal, dan salah, karena user
sudah menegosiasikan jawaban berbeda untuk masalah yang sama.

Bentuk yang benar: **snapshot berversi**. Tiap pembaruan bikin baris baru, dan
`Match.prediction_before_kickoff()` menyaring `created_at < kickoff_at`.
Efeknya sama dengan mengunci — versi yang ditulis sesudah peluit tidak bisa
menyamar jadi prediksi pra-laga — tanpa melanggar aturan dan tanpa mengklaim
sesuatu yang tidak bisa dilacak app (prinsip desain nomor 3).

Modelnya: `PredictionSnapshot` → `HypothesisItem` (KENA/BELUM/MELESET + bukti
angka) dan `LineupSlot` (11 posisi, keyakinan, penanda pemain kunci).
Diisi lewat Django admin; tidak diekspos lewat DRF karena API-nya `AllowAny`.

`created_at` memakai **`auto_now_add`, bukan `auto_now`**. Tiga model lain di
file yang sama pakai `auto_now` karena memang mau tahu sentuhan terakhir;
menyalin polanya ke sini akan menulis ulang cap waktu tiap kali baris disimpan,
membuat prediksi pra-laga bercap sesudah laga dan mengosongkan Cek Prediksi
tanpa gejala. Ada test regresinya.

### 18.2 Koordinat ESPN: skalanya beda DAN arahnya terbalik

Awalnya terbaca sebagai "303 play memakai skala 0..100". Data membantah
tafsiran sederhana itu:

| | gol | tembakan tepat | pelanggaran |
|---|---|---|---|
| format lama (0..1) | **0.225** | 0.290 | 0.632 |
| format baru (÷100) | **0.915** | 0.834 | 0.513 |

Di format lama 0 = di garis gawang yang diserang; di format baru justru 100.
Membagi 100 saja akan membuat **gol dibaca sebagai kejadian paling tidak
berbahaya di lapangan**. Konversinya `1 - x/100`.

Kenapa lolos sekian lama: `_danger` menjepit hasilnya ke `[0,1]`, jadi nilai
0..100 tidak pernah error — play biasa cuma diam-diam dapat bahaya minimum dan
pelanggaran dapat maksimum.

Deteksi **per laga**, bukan per nilai: 0.5 sah di kedua format, tapi satu laga
tidak pernah mencampur keduanya (dicek ke 419 laga: nol yang campur).

### 18.3 Metrik duplikat yang menyesatkan

Angka "55 kunci nama muncul lebih dari sekali" yang dipakai sebagai alarm
ternyata sebagian besar **bukan duplikat**. Kuncinya (inisial, nama belakang) —
cukup untuk mencocokkan 'S. Amrabat' dengan 'Sofyan Amrabat', tapi begitu
dipakai se-liga ia menyatukan *Aaron* vs *Alfie* Cresswell, *Abdou* vs *Amad*
vs *Amadou* Diallo, *André* vs *Angel* Gomes.

**Sebuah metrik pemantauan bisa jadi sumber alarm palsu yang menyita perhatian
dari kerusakan nyata.** Metrik yang benar: berapa pemain yang statistiknya
terbelah — dan itu sekarang nol.

Dan cek "nol statistik terbelah" yang saya laporkan lebih awal **buta** untuk
kasus terpenting: `Amad Diallo` (#34, 146 laga) vs `Amad Diallo Traore` (#1481,
32 laga) — kuncinya membaca `diallo` vs `traore` sebagai dua orang, padahal
kedua record muncul di 32 laga yang sama persis.

### 18.4 `pull_xg_understat`: empat cacat yang saling menyembunyikan

1. Melahirkan 16 Player duplikat (Understat pakai nama lengkap: 'Ezri Konsa
   Ngoyo', 'Iyenoma Destiny Udogie').
2. Nama tersimpan dengan entitas HTML mentah (`Jake O&#039;Brien`) — yang
   sekaligus menghalangi pencocokan ke record aslinya.
3. `MatchShot.source` tidak diisi: 1.069 baris kosong, filter per sumber
   mengembalikan nol.
4. `_save_shots` menghapus **seluruh** tembakan laga termasuk milik FotMob.
   Yang menyelamatkan selama ini cuma urutan cron, dan itu bukan jaminan.

Pencocokan barunya lewat himpunan bagian token nama, dengan syarat **tepat satu
kandidat**: Nottingham Forest punya 'Jair Cunha' DAN 'Jair Paula', jadi nama
'Jair' saja tidak boleh dipaksa memilih.

**Sengaja tidak digabung** dan butuh mata manusia: 'Yehor Yarmolyuk' vs
'Yarmoliuk' (beda transliterasi), 'Chimuanya' vs 'Lesley Ugochukwu' (beda nama
depan), serta 'Toti', 'Jair', 'Sávio' (nama satu kata, bukti terlalu lemah).

### 18.5 Penggabungan tim melahirkan laga ganda

Melebur Team 'Wolves' ke 'Wolverhampton Wanderers' menyisakan **6 pasang Match
kembar** — tiap pertemuan tersimpan dua kali di bawah dua record tim, dan baru
terlihat kembar setelah timnya jadi satu. Premier League tercatat **40 laga per
musim** padahal 38.

Event **wajib** di-dedup sebelum absorb: `MatchEvent` tidak punya unique
constraint, jadi memindahkan begitu saja menggandakan gol dan kartu. Kembaran
yang statistiknya kosong pun tetap membawa 15-23 event dari provider lain.

Pelajaran umum: **penggabungan di satu lapisan melahirkan duplikat di lapisan
di atasnya.** Sesudah menggabung Team, periksa Match. Aturannya sekarang jalan
otomatis tepat sesudah `_merge_teams`.

### 18.6 Nol-palsu ESPN

Untuk sebagian laga ESPN mengirim blok statistik lengkap yang seluruh isinya
`'0'`. Karena non-null, angka itu lolos semua penyaring:

| musim | dengan nol-palsu | sebenarnya | laga nol |
|---|---|---|---|
| 2021 | 51,8% | 53,8% | 2 |
| **2022** | **49,4%** | **56,4%** | **8** |
| 2023 | 49,8% | 52,5% | 3 |
| 2024 | 52,9% | 54,8% | 2 |

Selisih 7 poin di 2022 cukup untuk mengarang tren "MU ambruk lalu bangkit" yang
seluruhnya artefak data.

Deteksinya penguasaan bola **dan** total umpan sama-sama nol. Nol tembakan saja
tidak cukup — itu jarang tapi sah; nol penguasaan sekaligus nol umpan tidak
mungkin untuk tim yang benar-benar bermain.

### 18.7 Keadaan akhir

| | |
|---|---|
| Match | 817 (laga ganda: 0) |
| MatchPlay | 31.073 (`field_x > 1`: 0) |
| PlayerMatchStatistics | 27.731 (yatim: 0) |
| MatchShot | 9.700 (tanpa `source`: 0) |
| Laga MU punya momentum | 421 / 431 |
| Laga PL per musim | 38 untuk seluruh 2019–2025 |
| Skuad MU aktif | 38 |
| Statistik terbelah | 0 |
| Test | 114 lolos |

### 18.8 Yang masih menggantung

- ~~**Backup off-server**~~ — **SELESAI 23 Agu 2026.** Lihat 18.9.

<!-- catatan lama, disimpan karena isinya jebakan yang masih berlaku -->
- **Backup off-server — separuh jalan.** `scripts/backup-db.sh` sudah jadi dan
  terpasang di cron (03:30 WIB), `rclone v1.75.0` terpasang di `~/bin/rclone`
  (checksum diverifikasi terhadap SHA256SUMS resmi). Dump harian jalan dan
  berotasi (3 lokal). **Yang belum: OAuth Google Drive**, dan itu memang harus
  dikerjakan pemilik akun — token tidak boleh lewat chat atau ditulis agen.
  Sampai itu beres, salinannya masih di server yang sama dengan Postgres-nya.

  Tiga jebakan yang ditemui waktu menulis skrip ini, semuanya khas host ini:
  1. **`eval` untuk membaca `.env` itu berbahaya.** Password produksi
     mengandung karakter khusus; `eval` menafsirkan potongannya sebagai nama
     variabel, skrip mati dengan `unbound variable`, dan potongan password itu
     **ikut tercetak ke log**. Sekarang dipakai `printf -v`, yang menugaskan
     nilai tanpa pernah menafsirkannya sebagai kode.
  2. **Tidak ada `/dev/fd`.** Process substitution (`< <(grep ...)`) mati
     dengan `No such file or directory`. `.env` dibaca langsung `< .env` dan
     disaring `case` di dalam loop.
  3. **Rotasi lokal harus mendahului urusan remote.** Versi pertama merotasi di
     akhir, jadi selama Drive belum tersambung skrip berhenti duluan dan dump
     16 MB/hari menumpuk diam-diam sampai kuota habis.
- 6 record understat-only yang sengaja dibiarkan (lihat 18.4).
- **10 laga MU tanpa play-by-play (421/431).** Sempat dikira backfill yang
  terpotong — koneksi SSH memang putus di tengah (`broken pipe`, exit 255) —
  tapi penarikan ulang menghasilkan celah yang **identik**, jadi ini batas
  sumber, bukan kegagalan kita. Tiga sebab berbeda:
  1. **4 laga tanpa ref ESPN sama sekali** (Dortmund 2023, Copenhagen ×2,
     Plzen) — laga cup Eropa. Endpoint jadwal ESPN mengembalikan 0 fixture
     untuk `uefa.champions` di musim-musim lama, jadi ESPN tidak pernah
     menyentuhnya. Isinya kosong total, cuma skor dari Highlightly.
  2. **5 laga punya ref dan ingest ESPN** tapi bagian `commentary`-nya memang
     kosong di sisi ESPN — kebanyakan laga persahabatan pramusim.
  3. **1 laga sehat kecuali komentarnya** (West Ham 10 Feb 2026: 12 event,
     41 statistik, 5 sumber).

  Pelajaran operasional: perintah panjang di server **wajib** `nohup` dan
  ditaruh di `~/mu-analytics/scripts/` — `/tmp` di host ini di-mount `noexec`,
  jadi skrip di sana gagal dengan `Permission denied` yang menyesatkan.
- Halaman Jadwal masih dibatasi 100 laga tanpa filter musim, jadi sebagian
  besar hasil backfill belum bisa dijangkau lewat UI.
- Halaman Statistik masih terblokir: `passes_total` dan field progresif tidak
  ada di skema, `shots_faced` nol di musim 2025 dan 2026.


---

## 19. Backup off-server ke Google Drive

Selesai 23 Agustus 2026. Rantainya: `pg_dump` → rotasi lokal → `rclone` →
Google Drive, tiap hari 03:30 WIB lewat cron.

### 19.1 Bentuknya

- `rclone v1.75.0` di `~/bin/rclone`, checksum diverifikasi terhadap
  `SHA256SUMS` resmi sebelum dijalankan.
- Remote `gdrive:` dengan scope **`drive.file`** — rclone hanya bisa menyentuh
  file yang ia buat sendiri, sisa isi Drive tidak terlihat olehnya.
- Client OAuth **milik sendiri**, bukan client_id bersama milik rclone. Ini
  bukan kemewahan: rclone memperingatkan client_id bersamanya pensiun "selama
  2026", dan saat ini dipasang sudah Agustus 2026. Backup adalah tempat paling
  buruk untuk menyimpan tanggal kedaluwarsa yang sudah diketahui.
- Consent screen di-**publish ke Production**. Kalau ditinggal di *Testing*,
  refresh token Google kedaluwarsa tiap 7 hari dan backup putus tiap minggu —
  diam-diam, karena yang gagal cuma satu baris di `cron.log`.
- Retensi: 3 salinan lokal, 14 hari di Drive.
- Kredensial tidak pernah lewat agen: token dibuat pemilik akun lewat
  `rclone authorize` di mesinnya sendiri, ditempel langsung ke prompt server.

### 19.2 Empat jebakan waktu menulis skripnya

Semuanya khas host ini dan semuanya sudah menggigit sekali:

1. **`eval` untuk membaca `.env` mencetak password ke log.** Password produksi
   mengandung karakter khusus; `eval` menafsirkan potongannya sebagai nama
   variabel, skrip mati dengan `unbound variable`, dan potongan password itu
   ikut tercetak. Diganti `printf -v`, yang menugaskan nilai tanpa pernah
   menafsirkannya sebagai kode.
2. **Tidak ada `/dev/fd`.** Process substitution (`< <(grep ...)`) mati dengan
   `No such file or directory`. `.env` dibaca langsung `< .env`, disaring
   `case` di dalam loop.
3. **Rotasi lokal harus mendahului urusan remote.** Versi pertama merotasi di
   akhir, jadi selama Drive belum tersambung skrip berhenti duluan dan dump
   16 MB/hari menumpuk sampai kuota habis.
4. **`/tmp` di-mount `noexec`.** Skrip di sana gagal dengan `Permission denied`
   yang menyesatkan. Semua skrip tinggal di `~/mu-analytics/scripts/`.

### 19.3 Sejauh apa restore-nya benar-benar diuji

Ini penting dicatat jujur, karena "backup berhasil" sering berarti "file
terunggah" dan bukan "data bisa kembali".

Yang **sudah** dibuktikan, dengan file diunduh ULANG dari Drive (bukan salinan
lokal):

- SHA256 identik dengan dump di server — file utuh, tidak terpotong.
- Arsipnya valid: 29 tabel, 139 index/constraint terbaca `pg_restore --list`.
- Datanya benar-benar terbaca dan cocok jumlahnya dengan produksi:

  | tabel | produksi | dari dump Drive |
  |---|---|---|
  | `matches_match` | 817 | 817 |
  | `matches_playermatchstatistics` | 27.731 | 27.731 |
  | `matches_matchplay` | 31.073 | 31.073 |
  | `matches_matchshot` | 9.700 | 9.700 |
  | `players_player` | 3.137 | 3.137 |
  | `players_team` | 89 | 89 |

Yang **belum** dibuktikan: restore penuh ke database hidup. Hosting ini
menolak `createdb` dari command line (`no pg_hba.conf entry ... database
template1`) — database hanya bisa dibuat lewat UI cPanel. Jadi kalau suatu
saat benar-benar perlu memulihkan, langkah pertamanya bikin database baru
lewat cPanel, lalu:

```bash
pg_restore -h localhost -U <user> -d <db_baru> --no-owner --no-privileges <file.dump>
```

Catatan kecil: `rclone config userinfo` tidak jalan dengan scope `drive.file`
(tidak ada akses ke profil akun). Verifikasi "akunnya benar" dilakukan dengan
melihat file muncul di Drive akun yang dimaksud, bukan lewat perintah.


---

## 20. Sesi 23 Agustus (lanjutan): lima pekerjaan

Dipetakan lebih dulu oleh lima penyelidik paralel + satu pemeriksa silang.
Pemeriksaan silang itu yang paling berharga — ia menemukan dua hal yang akan
menggigit kalau langsung dikerjakan.

### 20.1 Urutan pengerjaan ternyata bukan preferensi

Rencana awal: kerjakan retensi `RawPayload` kapan saja. Pemeriksa silang
menunjukkan itu salah: **penyaring inkremental ESPN menghapus ~744 penulisan
ulang `RawPayload` per hari**, sehingga justifikasi utama field
`payload_sha256` (menghindari menimpa payload identik) hilang begitu penyaring
mendarat. Migrasi yang hampir ditulis itu akan membeli mendekati nol.
Urutannya jadi wajib: ingest dulu, ukur ulang, baru putuskan.

### 20.2 Penyaring yang salah tempat membekukan laga live — diam

`resolve_match` memakai `Match.objects.filter(...).update(**defaults)` yang
menimpa `status`. Kalau penyaring "sudah pernah ditarik" ditaruh sesudah laga
disimpan, laga yang ditarik saat masih jalan akan dilewati **selamanya** dan
datanya beku di potret menit-60.

Syaratnya jadi dua, dan yang kedua yang menyelamatkan: status **di DB** sudah
final DAN sudah ada `MatchIngest`. Status dibaca dari baris LAMA, bukan dari
payload yang baru datang — laga live tetap dapat `MatchIngest`, jadi kalau
syaratnya cuma "pernah ditarik", pembekuan itu terjadi.

Ini diuji dengan sengaja membuatnya salah: pengecekan status dilepas, dua test
langsung merah (laga live dan laga tertunda), lalu dikembalikan. Unit test yang
cuma memanggil `_already_final` tetap hijau walau penyaringnya salah tempat —
itu sifat test-nya, bukan retorika.

Hasil nyata: 8 dari 8 fixture dilewati, waktu jalan **90 detik → 9 detik**,
~670 panggilan ESPN hilang per hari.

### 20.3 Alarm palsu yang sudah menyala

`pull_match_events_pl` tidak pernah menulis `MatchIngest`, sementara
`source_health.py` melacak `PREMIER_LEAGUE` dengan ambang (26, 72) jam yang
dibaca dari tabel itu. Nol baris = umur tak hingga = kartu Kesehatan Sumber
memajang "berhenti" untuk feed yang jalan tiap malam. Persis kelas kegagalan
yang jadi tema bagian 17.

### 20.4 Jadwal: jebakan GROUP BY

`Match.Meta` punya `ordering = ['kickoff_at']`, dan Django menyeret kolom
ordering ke `GROUP BY`. Query facet tanpa `.order_by()` kosong mengembalikan
**288 baris** (satu per kickoff unik), bukan 8. Ada test yang menjaganya.

Pengelompokan 44 nama liga mentah jadi empat kategori dibuat sebagai fungsi
murni di `matches/competitions.py`, **bukan** model `Competition` — model itu
butuh migrasi, pemetaan id lintas provider, dan penggabungan laga ganda;
halaman Jadwal tidak perlu menunggu itu.

Ini juga **test view pertama** di repo ini. Seluruh 149 test sebelumnya ada di
lapisan data, nol menyentuh view — padahal tahap berikutnya 100% kerja view.

### 20.5 Prediksi susunan: yang jujur dan yang tidak

Susunan starter dibaca dari `formation_x`/`formation_y` FotMob — 11 koordinat
per laga. Field `is_starter` memang tidak ada, dan kolom `starter` yang sempat
dicoba isinya 0 untuk semua baris.

Dua aturan label salah dan ketahuan waktu diuji lintas formasi, bukan lewat
data: lini tengah 2 pemain (double pivot 4-2-3-1) tidak tertangani sama sekali
padahal itu kasus paling sering, dan lini tengah lebar dipetakan jadi wing-back
di semua formasi padahal kalau lini belakang sudah berisi 4, yang lebar di
tengah itu sayap.

**Yang paling penting soal angkanya:** persentase di sini adalah *frekuensi
historis slot*, bukan peluang pemain start. Tidak ada dasar jujur untuk
menghitung peluang — data cedera seluruhnya `RETURNED`, rotasi/skorsing/
transfer tidak terekam di mana pun. Menyebutnya "80% kemungkinan start" akan
jadi angka yang meyakinkan tapi tidak berdasar, persis jenis kesalahan yang
bikin analis berhenti percaya. Batas itu ditulis di `note` tiap snapshot.

Snapshot pertama tersimpan **7 hari sebelum kick-off** untuk MU vs Ipswich.

Satu bug yang layak dicatat: `before_kickoff` dan `lead_time` itu **property**,
bukan method. Command memanggilnya dengan tanda kurung dan mati `TypeError` —
tapi baru di baris pesan sukses, SESUDAH snapshot terlanjur tertulis. Jadi
perintahnya kelihatan gagal padahal datanya masuk; yang menyelamatkan dari
duplikat cuma pengecekan idempoten.

### 20.6 Retensi RawPayload: alatnya dibuat, sengaja tidak dijalankan

Dua asumsi awal keliru, keduanya ketahuan dari pengukuran:

- Tabel ini **57 MB di disk**, bukan 158 MB. Angka `size_bytes` itu panjang
  JSON mentah; Postgres meng-kompres JSONB lewat TOAST. Database totalnya
  119 MB, disk server sisa 314 GB — **tidak ada krisis ruang**.
- **Retensi berbasis umur tidak bisa dipakai.** `fetched_at` itu `auto_now`,
  jadi mencatat penulisan terakhir, bukan penangkapan pertama. Selama ESPN
  masih menarik ulang semuanya tiap 10 menit, tiap payload berumur nol
  selamanya; dan sesudah penyaring inkremental dipasang, semuanya berhenti
  diperbarui di hari yang sama sehingga seluruh tabel jatuh ke ambang umur
  BERSAMAAN.

Kebijakannya jadi yatim lalu musim. Dry run: 0 yatim, 309 payload musim
2019–2023 memenuhi syarat. **Tidak dijalankan.** Menghapus bahan putar ulang
lima musim untuk menyelesaikan masalah ruang yang tidak ada itu keliru, dan
menariknya ulang butuh 309 panggilan ke API tidak resmi. Tidak masuk cron.

### 20.7 Yang masih menggantung sesudah sesi ini

- **Hipotesis taktik untuk laga Ipswich** — ini kerja analis, bukan app.
  Susunannya sudah tersimpan; tiga kartu hipotesis masih kosong.
- **`MatchIngest.rows` jadi omong kosong.** Field itu diisi total berjalan
  seluruh run, bukan per laga, dan sesudah penyaring aktif angkanya anjlok.
  Fungsinya justru mengendus penarikan yang "berhasil tapi kosong".
- **Dua kosakata filter** untuk satu konsep: `MatchViewSet` (DRF) sudah punya
  `?season=` dan `?all=true`, halaman Jadwal memakai `?musim=` dan `?all=1`.
