# Handoff: MU Analytics Console — Divisi Analisis Indomanutd Jogja

## Overview

Web app internal untuk divisi analisis komunitas suporter Manchester United (Indomanutd Jogja regional Jogja). Dipakai tiga tim kecil analis, di laptop, dengan empat pekerjaan utama:

1. **Live pundit** — dipakai sambil nobar dan siaran TikTok. Menyajikan sudut pandang siap ucap berbasis data, bukan tabel mentah.
2. **Pra-laga** — prediksi susunan, hipotesis taktik, head to head, pemain kunci, fakta pendukung. Saat laga berjalan halaman ini berubah jadi alat cek prediksi.
3. **Pasca-laga** — laporan otomatis, angka penentu, nilai pemain, saved moments per laga, dan generator prompt untuk bikin konten socmed.
4. **Bursa transfer** — indeks kebutuhan skuad per posisi, papan rumor bertahap, neraca bursa, spesifikasi profil pemain.

Ditambah tiga halaman rujukan: Skuad (rekonsiliasi konflik sumber + ketersediaan), Statistik (basis data pemain, filter musim dan kompetisi, kolom bisa disortir), Berita (feed bertingkat + sentimen + kesehatan sumber).

Bahasa antarmuka: **Indonesia**, dengan istilah teknis sepak bola dibiarkan dalam bentuk aslinya (xG, xA, xT, PPDA, PSxG, build-up, rest-defence, second ball, CB/LB/CDM/CM/AM/CF/RW).

## About the Design Files

File di bundel ini adalah **referensi desain yang dibuat dalam HTML** — prototipe yang menunjukkan tampilan dan perilaku yang diinginkan, bukan kode produksi untuk disalin langsung. `.dc.html` adalah format prototipe (React yang dirender dari template inline-style); jangan diadopsi sebagai arsitektur.

Tugasnya: **membangun ulang desain ini di codebase target** dengan pola dan library yang sudah ada di sana. Kalau belum ada codebase, pilih framework yang paling sesuai (rekomendasi: Next.js + TypeScript + Tailwind, dengan backend job scheduler untuk penarikan data) dan implementasikan di sana.

Semua angka di prototipe adalah **data contoh**. Yang harus dipertahankan adalah struktur panel, hierarki informasi, dan aturan penyajian — bukan angkanya.

## Fidelity

**High-fidelity.** Warna, tipografi, spasi, dan status interaksi sudah final. Bangun ulang dengan presisi menggunakan library codebase target.

---

## Prinsip Desain (jangan dilanggar saat implementasi)

1. **Kiri untuk yang dibaca, tengah untuk yang dilihat, kanan untuk yang dipantau.** Susunan kolom tiap halaman mengikuti ini.
2. **Setiap angka membawa sumbernya.** Chip sumber (`sumber: A+C`) muncul di kartu, dan panel Kesehatan Sumber menampilkan status tiap feed. Kalau tidak jelas asal datanya, jangan ditampilkan.
3. **App hanya mengklaim apa yang benar-benar bisa dilacaknya.** Tidak ada "diperiksa oleh X" tanpa login dan pencatatan aksi. Tidak ada "sudah diposting" tanpa integrasi platform. Ini keputusan produk yang sudah dinegosiasikan dengan user — jangan tambahkan klaim baru yang tidak punya sumber.
4. **App tidak menyimpulkan, dia menyiapkan bukti.** Kesimpulan tetap dari analis. Karena itu ada skor keyakinan dan indikator kekuatan bukti (3/3 kuat, 2/3 sebagian).
5. **Konvensi skor: Manchester United selalu ditulis lebih dulu.** `3–1` berarti United menang, apa pun venue-nya. Kandang/tandang dibaca dari keterangan terpisah. Berlaku di semua halaman.

---

## Design Tokens

### Warna

| Token | Hex | Pemakaian |
|---|---|---|
| bg | `#0A0B0D` | Latar halaman |
| nav | `#0E0F12` | Rel navigasi, bar atas |
| panel | `#121317` | Latar panel/kartu |
| inset | `#0E0F12` | Latar kotak di dalam panel |
| line | `rgba(255,255,255,.07)` | Border panel |
| line-row | `rgba(255,255,255,.045)` | Pemisah baris tabel |
| text | `#E8E9EB` | Teks utama |
| text-2 | `#C7CCD3` | Teks sekunder |
| text-3 | `#B9C0C9` | Body paragraf |
| dim | `#8E959E` / `#7E858F` | Keterangan |
| dim-2 | `#5A616B` / `#6E757F` | Meta, label sumber |
| accent | `#D6263A` | Aksen utama (United) |
| accent-hover | `#F2495C` | Hover tombol primer |
| opponent | `#5B77A8` | Data lawan |
| positive | `#3BD08C` (isi `#00C271`) | Baik, terkonfirmasi, kena |
| warning | `#E4B84A` | Perlu perhatian, sebagian |
| info | `#4C7DF0` / `#7C9FF5` | Kategori pemain |
| pitch | `#0D1410` | Latar lapangan |

Latar berwarna transparan yang dipakai: `rgba(214,38,58,.12–.14)` (aksen aktif), `rgba(0,194,113,.13)`, `rgba(228,184,74,.14)`, `rgba(76,125,240,.14)`.

### Tipografi

- **Display / judul / label**: `Barlow Condensed` — 600–700, `text-transform: uppercase`, `letter-spacing .04–.16em`. Judul panel 14–15px, judul halaman 22–46px.
- **Body**: `Barlow` — 400–600, 11–16px, `line-height 1.3–1.65`.
- **Angka & meta teknis**: `JetBrains Mono` — 400–700, 8–40px. Semua angka, timestamp, label sumber, dan skor pakai font ini.

Aturan: label kecil selalu uppercase + letter-spacing lebar (kesan siaran televisi). Angka besar selalu monospace.

### Lainnya

- Radius: `6px` panel, `4px` kotak dalam, `3px` tombol dan chip, `2px` tag kecil.
- Spasi: gap antar panel `14px`, padding panel `15–16px`, padding baris tabel `10–11px 16px`.
- Tidak ada shadow. Kedalaman dibuat dari perbedaan latar dan border.
- Animasi: hanya `pulse` (opacity 1 → .25, 1.6s ease-in-out infinite) pada titik indikator live.

---

## Rangka Aplikasi

```
┌────┬──────────────────────────────────────────────┐
│rel │ bar atas (52px, sticky)                      │
│74px├──────────────────────────────────────────────┤
│stic│ isi halaman (padding 16px 20px 28px)         │
│ky  │                                              │
└────┴──────────────────────────────────────────────┘
```

- **Rel kiri** 74px, `position: sticky`, tinggi 100vh. Logo blok merah 30×30 bertuliskan MU (bukan lambang klub — hindari aset ber-hak cipta). Tujuh item: Live, Pra, Pasca, Bursa, Skuad, Statistik, Berita. Item aktif dapat bar merah 3px di sisi kiri. Ikon pakai karakter monospace (◉ ◧ ▤ ⇄ ⚕ Σ ✦), label uppercase 10px.
- **Bar atas**: judul "Meja Analisis", nama halaman aktif (monospace), chip status sumber, indikator Live/Idle.
- **Lebar minimum konten 1240px.** Di bawah itu halaman scroll horizontal, tidak boleh remuk. Ini disengaja: app hanya untuk laptop.

---

## Halaman

### 1. Live — dua kondisi

Kondisi ditentukan apakah ada laga berjalan.

#### 1a. Laga berjalan

Grid: `404px | minmax(520px,1fr) | 306px`, gap 14px.

**Strip pertandingan** (full width, tinggi ~90px, dibagi lima seksi dengan border pemisah):
kompetisi + venue + waktu WIB · nama kedua tim dengan xG masing-masing dan skor besar 34px monospace · menit berjalan merah 26px + babak · grafik momentum 15 menit terakhir (dua garis SVG: merah solid United, abu putus-putus lawan, garis tengah tipis).

**Bahan Pundit** (kolom kiri, `max-height 718px`, scroll sendiri):
Header dengan judul + hitungan sudut pandang + lima chip filter (Semua, Taktik, Pemain, Pola, Bola Mati).
Tiap kartu: border kiri 2px berwarna kategori (Pola `#D6263A`, Pemain `#4C7DF0`, Taktik `#E4B84A`, Bola Mati `#00C271`) · menit merah monospace · tag kategori · skor keyakinan (`yakin 0.86`) · judul klaim 17px Barlow Condensed 600 · paragraf penjelasan 12.5px · bukti angka (tiga kotak metrik, atau bar chart mini, atau tanpa visual) · tombol `+ Save` (primer merah) dan `Salin kalimat` (outline) · label sumber (`sumber: A+C`).

**Lapangan** (kolom tengah): header dengan formasi + empat tombol lapisan (Jaringan, Heatmap, Zona, Tembakan). Lapangan `padding-top: 62%`, latar `#0D1410`, garis `rgba(255,255,255,.13)`: border luar (inset 12px), garis tengah, lingkaran tengah 16%, dua kotak penalti (15% lebar, top/bottom 24%), dua kotak gawang (6% lebar, top/bottom 36%).

Empat lapisan, saling menggantikan:
- **Jaringan**: SVG garis antar pemain (tebal = volume umpan, warna merah untuk jalur utama) + 11 bulatan pemain absolut (28–42px, diameter = jumlah sentuhan, nomor punggung monospace di tengah; pemain kunci dapat isi merah transparan + border `#D6263A`).
- **Heatmap**: lima blob `radial-gradient(circle, rgba(214,38,58,.32–.75), transparan 70%)`.
- **Zona**: grid 6×3 di dalam inset 12px, latar `rgba(214,38,58,.14–.42)` untuk zona dikuasai United dan `rgba(91,119,168,.18–.36)` untuk lawan, angka persentase di tengah.
- **Tembakan**: bulatan absolut, diameter 11–26px mengikuti nilai xG, merah untuk United, biru untuk lawan; xG ditulis di dalam bulatan besar.
Tiap lapisan punya legenda kecil di kanan bawah dengan latar `rgba(0,0,0,.55)`.

**Bulatan pemain bisa diklik** dan membuka dialog detail pemain (lebar 760px): nomor, nama, posisi, menit, nilai, empat metrik utama, sebaran aksi di lapangan mini, grafik per 15 menit, satu kalimat kesimpulan, tombol `+ Save`. Set metrik dan judul grafik **berbeda per posisi** — kiper memakai penyelamatan dan aksi kiper, bek tengah aksi bertahan, pemain yang metriknya mengandung xT memakai xT per 15 menit, sisanya keterlibatan per 15 menit. Nama di panel Skuad membuka dialog yang sama, jadi satu komponen dipakai dua tempat.

Di bawah lapangan: strip enam metrik (Penguasaan, Tembakan, PPDA, Sepertiga akhir, Akurasi umpan, Garis tahan m).

**Game Highlights** (kolom tengah, bawah): tiga kartu klaim besar, masing-masing dengan ringkasan bukti dan indikator kekuatan (`bukti 3/3 · kuat` hijau, `bukti 2/3 · sebagian` kuning) plus tautan `Lihat bukti`. Isi ketiga kartu **berganti mengikuti fase laga** (babak pertama, jeda babak, babak kedua, jeda sebelum extra time).

Klik kartu membuka **dialog bukti klaim** (lebar 700px, overlay `rgba(0,0,0,.72)`): daftar syarat yang diperiksa model, tiap baris berisi label syarat, nilai sebenarnya, ambang yang dipakai, kode sumber, dan tanda terpenuhi (✓ hijau) atau belum (· kuning); rasio bukti di kanan atas; lalu blok kalimat siap ucap dengan tombol `+ Save` dan `Salin kalimat`, ditutup catatan cara menyampaikan (fakta kalau 3/3, dugaan kalau 2/3). Aturan implementasi: ambang disimpan bersama klaim, jangan dihitung ulang di UI.

**Kolom kanan**: 
- *Skuad* — 8 baris pemain di lapangan: nomor punggung, nama, satu baris kontribusi kunci, nilai 0–10 (hijau ≥7.5, putih 6.5–7.4, kuning <6.5, selalu satu desimal).
- *Saved Moments* — hasil klik `+ Save`, tiap baris menit + kalimat, tombol `Kirim ke Pasca` dan `Hapus`.
- *Kandidat Rotasi* — dihitung dari beban menit dan output 20 menit terakhir. **Bukan** "siapa yang pemanasan": tidak ada feed data yang tahu itu.

#### 1a-2. Jeda (jeda babak / jeda sebelum extra time)

Saat fase laga bukan "berjalan", strip pertandingan **diganti** panel jeda di posisi yang sama (border `rgba(214,38,58,.3)`): judul fase, hitung mundur ke babak berikutnya, catatan singkat, tombol ke Game Highlights, lima angka penentu babak yang baru selesai, lalu dua kolom — *yang layak dibahas* (angka besar + kalimat) dan *yang perlu berubah* (judul tindakan + alasan). Isi kedua kolom, angka xG, daftar Kandidat Rotasi, dan set Game Highlights semuanya menyesuaikan fase.

Fase datang dari feed, bukan dihitung sendiri: `berjalan` | `jeda babak` | `jeda extra time`. Bahan Pundit tidak menerima event baru saat jeda, dan itu memang alasan panel ringkasan mengambil alih ruang paling atas.

#### 1b. Tidak ada laga (idle)

Grid: `minmax(520px,1fr) | 380px`.

- **Kartu hitung mundur**: label "tidak ada pertandingan berjalan", laga berikutnya (kompetisi + MD), nama laga 40px, venue + waktu WIB, hitung mundur merah 34px, tombol `Baca analisis pra-laga` dan `Buka laporan terakhir`.
- **Persiapan Divisi**: empat baris. Tiap baris punya kotak status (centang hijau / kotak kuning kosong), judul, baris meta monospace yang menjelaskan **siapa dan bagaimana**, chip pemilik (`SISTEM` = otomatis, `MANUAL` = harus ada orangnya), dan tombol aksi yang menavigasi ke halaman terkait. Legenda di atas menjelaskan arti kedua chip.
- **Jadwal Berikutnya**: tiga kartu laga, yang terdekat dapat border kiri merah.
- **Kesiapan Data** (kanan): status empat feed dengan titik hijau/kuning/merah dan keterangan (`siap`, `terbit 1 jam sebelum kick-off`, `6 jam tanpa data baru`).
- **Hasil Terakhir**: skor, lawan, xG, satu kalimat evaluasi hipotesis.

### 2. Pra — dua kondisi

Grid: `minmax(520px,1fr) | 380px`. Di atas grid ada bar identitas laga full width.

**Bar identitas**: label mode + nama laga 22px + kompetisi + venue + waktu WIB, lalu baris kedua di bawah pemisah:
- Mode rencana (belum kick-off): "Menyiapkan laga" · `Prediksi per 15 Agu 09:24` + penjelasan bahwa angka masih diperbarui otomatis sampai kick-off dan tiap konten membawa cap waktu ini.
- Mode laga berjalan: titik merah berdenyut + "Laga berjalan · cek prediksi" + penjelasan bahwa yang dibandingkan adalah prediksi terakhir sebelum kick-off.

Tidak ada mekanisme kunci atau approval. Framing yang sudah disepakati dengan user: **"sampai konten ini diunggah, beginilah prediksi kami"** — prediksi terus diperbarui otomatis sampai kick-off, dan tiap konten membawa cap waktu versi yang dipakai. Jangan menambahkan tombol lock, status "diperiksa oleh X", atau approval flow; app tidak punya login sehingga klaim itu tidak bisa dibuktikan.

**Cek Prediksi** (hanya saat laga berjalan, panel paling atas, border `rgba(214,38,58,.3)`): tiga kartu hipotesis dengan status `KENA` (hijau) / `BELUM` (kuning) / `MELESET` (merah) + bukti angkanya, ditambah baris akurasi susunan (`10 dari 11 tepat`). Ini pembeda utama produk: membuktikan analisis dibuat sebelum laga, bukan setelah fakta.

**Prediksi Susunan**: lapangan `padding-top: 56%`, 11 pemain absolut dengan bulatan 34px berlabel posisi (GK/RB/CB/LB/CM/RW/AM/LW/CF) dan nama di bawahnya. Posisi belum pasti diberi warna kuning + persentase keyakinan. Pemain kunci merah. **Orientasi: tim menyerang ke kanan, jadi bek kanan di bawah dan bek kiri di atas** (sama seperti tayangan televisi).

**Hipotesis Taktik**: tiga kartu, border atas berwarna, judul dugaan, penjelasan, dan rekam jejak (`muncul di 6 dari 8 laga · akurasi 62%`).

**Head to Head**: lima pertemuan terakhir. Tiap baris: tanggal, bar warna hasil (hijau menang, kuning imbang, merah kalah), nama laga (United dulu), skor, venue. Ditutup catatan agregat.

**Pemain Kunci**: dua kolom (United aksen merah, lawan aksen biru), tiga pemain masing-masing dengan satu angka pembeda dan satu kalimat konteks. Dipilih dari output per 90 menit, bukan dari nama besar.

**Kolom kanan**: Profil Lawan (enam bar horizontal), Duel Kunci (tiga kartu), Fakta Pendukung (enam fakta, tiap fakta membawa label sumber).

### 3. Pasca

Grid: `minmax(520px,1fr) | 420px`. Di atasnya bar **pemilih laga** full width: chip per laga (skor, lawan, tanggal), chip aktif dapat latar dan border merah.

Berpindah laga mengganti: identitas, judul dan isi laporan, empat angka penentu, nilai pemain, saved moments, isi prompt, dan draf caption.

- **Laporan Pertandingan**: baris identitas (nama laga + skor merah + kompetisi/tanggal/venue), judul 30px, dua paragraf 14px/1.65, tombol `Salin laporan` dan `Susun ulang`.
- **Angka Penentu**: empat kartu, angka 24px monospace + label, border kiri berwarna sesuai sifat angka.
- **Nilai Pemain**: nama, posisi, bar horizontal, nilai. Keterangan: "dihitung dari event laga".
- **Saved Moments**: milik laga itu, menit + kalimat, ditutup catatan bahwa isinya jadi bahan mentah generator prompt.
- **Generator Prompt** (kolom kanan) — **menggantikan pembuat gambar/carousel**. User tidak ingin app membuat gambar. App menghasilkan prompt siap tempel ke tools AI mana pun, di mana teks dan angkanya berasal dari data laga sehingga AI hanya mengerjakan visualnya.
  - Pemilih sumber: `Saved moments` / `Analisis sistem` / `Gabungan`.
  - Pemilih tipe konten: `Feed tunggal` (1:1) / `Carousel` (4:5, 1080×1350, 4 slide) / `Video / Reels` (9:16, naskah + arahan visual per adegan) / `Thread di X` (urutan tweet, satu angka per tweet) / `Story` (9:16). Tiap tipe mengganti bagian instruksi format di prompt, bukan datanya.
  - Kotak prompt monospace 10.5px, `white-space: pre-wrap`, `max-height 430px`, scroll.
  - Tombol `Salin prompt` selebar panel.
  - Blok caption di bawahnya dengan nada bisa diganti (Analis / Siaran / Socmed).

  Struktur prompt yang dihasilkan (pertahankan urutan dan aturannya): perintah + dimensi → **GAYA VISUAL** (token warna, tipografi, larangan foto pemain dan lambang klub, banyak ruang kosong) → **ATURAN TEKS** (tulis persis, jangan mengubah/membulatkan angka, bahasa Indonesia, jangan menambah kalimat) → **LAGA** → **DATA YANG BOLEH DIPAKAI** → **ISI TIAP SLIDE** → **FOOTER**.

### 4. Bursa

Grid: `320px | minmax(560px,1fr)`.

- **Indeks Kebutuhan Skuad** (kiri): tujuh posisi (CB, LB, CDM, CM, AM, Winger, CF) dengan skor 0–100, bar berwarna (merah mendesak, kuning menengah, biru aman), dan satu baris alasan. Dihitung dari beban menit, kurva usia, dan output dibanding tolok ukur posisi. **Dibaca lebih dulu daripada rumor** — kebutuhan ditentukan sebelum melihat nama.
- **Neraca Bursa** (kiri): masuk, keluar, dipinjamkan, pinjaman masuk, belanja bersih, plus chip kebutuhan terpenuhi (`CF ✓`, `CDM ~`, `CB ✗`).
- **Papan Rumor** (kanan): lima kolom tahapan — Rumor ~15%, Negosiasi ~40%, Tahap lanjut ~75%, Tes medis ~93%, Resmi 100%. Tiap kolom punya border bawah berwarna. Kartu: posisi + liga, usia + nilai + jumlah sumber yang sepakat, skor kecocokan dengan indeks kebutuhan + bar. **Tahapan ditentukan jumlah sumber kredibel yang sepakat, bukan ramainya perbincangan.**
- **Spesifikasi Profil**: empat kartu (Wajib ×2, Nilai plus, Rentang anggaran) berisi syarat teknis untuk satu posisi. **Ketujuh posisi punya spesifikasinya sendiri**, dan isi panel mengikuti posisi yang diklik di Indeks Kebutuhan — bukan hanya posisi paling mendesak.
- **Dialog prompt konten** (dibuka dari tombol `Buat prompt konten` di Spesifikasi Profil, lebar 820px): pemilih tipe konten yang sama seperti di halaman Pasca, kotak prompt monospace, tombol salin. Dibuat sebagai dialog, bukan panel yang membuka ke bawah — ini permintaan eksplisit user.

### 5. Skuad

**Konflik Sumber** (panel paling atas, border `rgba(228,184,74,.3)`): satu kartu per pemain yang statusnya berbeda antar sumber. Isinya nama + posisi, dua kotak pilihan berdampingan (sumber A dan sumber D, masing-masing dengan umur data dan status yang diklaim), catatan penjelas, dan tautan untuk membatalkan pilihan. Aturan: selama belum dipilih, status pemain itu di tabel bawah tertulis `Bentrok` dan diberi tanda jangan dipakai untuk konten; pilihan analis menimpa keduanya dan dicatat sebagai pilihan manual, bukan data sumber; susunan resmi yang terbit satu jam sebelum kick-off menimpa semuanya secara otomatis. Panel menyebut ketiga aturan itu di UI, bukan hanya di dokumen.

Di bawahnya satu tabel selebar halaman. Kolom: `200px 70px 120px 1fr 120px 90px` — Pemain, Pos, Status, Catatan, Perkiraan kembali, Beban 14 hr.
Status berupa pill: Bugar (hijau), Diragukan (kuning), Absen (merah), Dipinjamkan (biru). Kolom beban diwarnai sesuai risiko. Header menampilkan waktu pembaruan dan jumlah sumber yang direkonsiliasi.

### 6. Statistik

Kolom: `180px 60px repeat(9, minmax(0,1fr))` — Pemain, Pos, Min, G, A, xG, xA, Prog/90, Umpan%, Int/90, Sv%.

- **Filter musim**: chip (2026/27, 2025/26).
- **Filter kompetisi**: chip (Semua komp, Liga, Piala, Eropa). Menit dan angka total ikut menyesuaikan.
- **Sortir**: klik judul kolom mana pun. Klik pertama turun, klik lagi naik, panah `↓`/`↑` menandai kolom aktif dan diwarnai `#F2495C`. Baris tanpa data (mis. xG kiper) **selalu di bawah**, di kedua arah.
- Keterangan di kanan atas wajib menyebut mana yang total dan mana yang per 90, supaya angka tidak salah dikutip saat siaran.

### 7. Berita

Grid: `minmax(520px,1fr) | 340px`.

- **Umpan Berita**: tiap item punya tingkat A (hijau) / B (kuning) / C (merah) berdasarkan rekam jejak sumber, judul, isi, dan meta (`2 jam lalu · 6 sumber sepakat · agregat`). Aturan redaksi: A boleh langsung jadi konten, B harus disebut belum pasti, C tidak diangkat.
- **Sentimen Fans**: empat bar. Keterangan wajib menyebut ini diisi manual dari polling story dan kolom komentar, bukan angka otomatis.
- **Kesehatan Sumber**: status empat feed + legenda arti warna (hijau normal, kuning ada jeda tapi wajar, merah feed berhenti dan angkanya jangan dipakai sebelum dicek manual).

---

## Interactions & Behavior

| Aksi | Hasil |
|---|---|
| Klik item rel navigasi | Ganti halaman, bar merah pindah, nama halaman di bar atas berubah |
| Klik tombol lapisan lapangan | Ganti overlay (jaringan/heatmap/zona/tembakan), lapangan dan legenda ikut berganti |
| Klik `+ Save` di kartu pundit | Tambah item ke Saved Moments di kolom kanan (menit + kalimat), hitungan naik |
| Klik `Salin kalimat` | Salin klaim + angka pendukung ke clipboard (belum tersambung di prototipe) |
| Klik chip laga di Pasca | Ganti seluruh isi halaman ke laga itu |
| Klik chip musim/kompetisi di Statistik | Hitung ulang tabel |
| Klik judul kolom Statistik | Sortir, toggle arah |
| Klik chip sumber/tipe konten di Generator Prompt | Susun ulang isi prompt |
| Klik kartu Game Highlights | Buka dialog bukti klaim (syarat, nilai, ambang, sumber) |
| Klik bulatan pemain di Lapangan atau nama di Skuad | Buka dialog detail pemain, metrik menyesuaikan posisi |
| Klik posisi di Indeks Kebutuhan | Ganti isi Spesifikasi Profil |
| Klik `Buat prompt konten` di Bursa | Buka dialog prompt |
| Klik kotak sumber di Konflik Sumber | Tabel Ketersediaan ikut berubah, ditandai pilihan manual |
| Fase laga berubah jadi jeda | Strip diganti panel jeda, isi Game Highlights dan Kandidat Rotasi ikut berganti |
| Tombol aksi di Persiapan Divisi | Navigasi ke halaman terkait |
| Hover tombol primer | Latar `#D6263A` → `#F2495C` |
| Hover tombol outline / chip | Border → `rgba(255,255,255,.3)`, teks → `#fff` |

Tidak ada transisi halaman, tidak ada animasi masuk. Satu-satunya animasi adalah denyut indikator live.

## State Management

State di prototipe (jadikan acuan minimum):

```
view            'live' | 'pre' | 'post' | 'transfer' | 'squad' | 'players' | 'news'
matchLive       boolean          // ada laga berjalan; mengganti kondisi Live dan mode Pra
matchPhase      'berjalan' | 'jeda babak' | 'jeda extra time'
hlIdx           number | null    // klaim Game Highlights yang dialognya terbuka
playerNum       number | null    // pemain yang dialog detailnya terbuka
conflicts       { [playerId]: 'A' | 'D' | null }  // keputusan analis atas konflik sumber
needPos         'CB'|'LB'|'CDM'|'CM'|'AM'|'Winger'|'CF'  // posisi terpilih di Indeks Kebutuhan
marketPromptOpen boolean
layer           'network' | 'heat' | 'zone' | 'shots'
savedMoments    { time, text }[] // ditambah dari kartu pundit, terikat ke laga
matchIdx        number           // laga terpilih di halaman Pasca
statSeason      '2026/27' | '2025/26'
statComp        'Semua' | 'Liga' | 'Piala' | 'Eropa'
sortKey         'name'|'pos'|'min'|'g'|'a'|'xg'|'xa'|'prog'|'pass'|'int'|'sv'
sortDir         'asc' | 'desc'
promptSrc       'live' | 'sistem' | 'gabungan'
promptFmt       'single' | 'carousel' | 'video' | 'thread' | 'story'
captionTone     'Analis' | 'Siaran' | 'Socmed'
showProvenance  boolean          // tampilkan/sembunyikan chip sumber
```

Di implementasi nyata, `matchLive`, data laga, dan status feed datang dari server, bukan state lokal.

## Data & Sumber

User menggabungkan **beberapa penyedia data gratis** yang saling menutupi kekurangan (satu punya hasil laga tapi susunan lengkap, yang lain punya xG, dst). Ini bukan detail teknis, ini bagian dari desainnya:

- Tiap nilai yang ditampilkan harus membawa **asal sumber**, dan UI menampilkannya (`sumber: A+C`).
- Konflik antar sumber tidak disembunyikan. App **menandai** konflik dan menyerahkan keputusan ke analis (lihat baris keempat Persiapan Divisi).
- Tiap feed punya status kesegaran, dan status itu tampil di bar atas serta panel Kesehatan Sumber.
- **Pemetaan ID pemain antar sumber adalah pekerjaan wajib pertama.** Kalau satu sumber menulis "B. Fernandes" dan yang lain "Bruno Fernandes", statistiknya pecah jadi dua entitas dan seluruh app jadi salah.
- Kalimat pembanding seperti "terburuk keempat di liga" butuh **data seluruh liga**, bukan hanya Manchester United.

Entitas minimum: `Match`, `MatchEvent` (dengan koordinat x/y untuk pass network dan heatmap), `Lineup`, `Player`, `PlayerMatchStats`, `PlayerSeasonStats` (per kompetisi per musim), `Injury/Availability`, `TransferRumour` (dengan tahapan dan jumlah sumber), `NewsItem` (dengan tingkat reliabilitas sumber), `SourceHealth`, `SavedMoment`, `Hypothesis` (disimpan sebelum kick-off untuk bisa dievaluasi setelahnya).

Catatan penting: **`Hypothesis` dan prediksi susunan harus disimpan dengan timestamp sebelum kick-off.** Tanpa itu, panel Cek Prediksi dan angka akurasi tidak punya dasar.

## Assets

Tidak ada aset gambar. Tidak ada lambang klub, foto pemain, atau logo pihak ketiga — sengaja, untuk menghindari masalah hak cipta. Identitas visual dibangun dari warna, tipografi, dan grafis data. Blok merah bertuliskan "MU" di rel navigasi adalah penanda buatan sendiri, bukan lambang klub. Pertahankan pendekatan ini; kalau nanti butuh gambar, pakai aset yang komunitas buat sendiri.

Font dari Google Fonts: `Barlow Condensed` (400,500,600,700), `Barlow` (400,500,600), `JetBrains Mono` (400,500,700).

## Files

| File | Isi |
|---|---|
| `MU Analytics Console.dc.html` | Seluruh app: tujuh halaman + dua kondisi halaman Live + dua mode halaman Pra |
| `Panduan Console.dc.html` | Panduan internal untuk tim: tiap panel dijelaskan dengan tangkapan layarnya (apa ini, gunanya, cara pakai, kenapa ditaruh di situ) + kamus istilah |
| `Inventaris Card.dc.html` | **Baca ini sebelum menulis kode.** Inventaris 40 card di semua halaman, masing-masing dengan varian, penjelasan, dan rumus datanya dalam tiga bagian: data mentah yang dibutuhkan, langkah pengolahan, dan angka jadi yang tampil. Ini spesifikasi logika, bukan dokumen desain |
| `support.js` | Runtime prototipe, cuma supaya `.dc.html` bisa dibuka langsung di browser. Bukan bagian dari produk |
| `shots/*.png` | Screenshot panel yang dipakai di dokumen panduan |

Cara membaca `.dc.html`: template markup ada di dalam `<x-dc>`, logika dan data contoh ada di `class Component extends DCLogic` di bagian bawah file. Semua style inline. Buka langsung di browser untuk melihat hasilnya.

## Yang Belum Dibangun (sengaja)

Supaya tidak ditebak sendiri:

- Login dan pencatatan aksi. Karena itu tidak ada klaim "diperiksa oleh X".
- Integrasi API Instagram/TikTok. App tidak tahu konten mana yang sudah diposting.
- Pembuat gambar. Diganti generator prompt.
- Clipboard: semua tombol salin belum tersambung.
- Pemilih laga di halaman Pra (baru ada di Pasca). Butuh data profil lawan dan hipotesis per laga.
- Input manual untuk sentimen fans.

---

## Urutan Bangun (untuk Claude Code)

Dikerjakan berurutan. Tiap tahap punya syarat selesai yang bisa diuji, dan tahap berikutnya jangan dimulai sebelum syaratnya terpenuhi.

**Tahap 0 · Fondasi data.** Skema database untuk semua entitas di bagian *Data & Sumber*, plus tabel `source` dan `ingest_log`. Yang paling penting: tabel pemetaan ID pemain antar sumber (`player_source_map`) dengan pencocokan manual sebagai jalan keluar. *Selesai kalau:* satu pemain dari tiga sumber berbeda menyatu jadi satu baris `player`, dan tidak ada nama ganda di tabel statistik.

**Tahap 1 · Penarikan dan rekonsiliasi.** Job penarikan per sumber dengan jadwal masing-masing, penyimpanan mentah sebelum diolah (supaya bisa diputar ulang tanpa menarik lagi), aturan prioritas sumber, dan pendeteksi konflik. *Selesai kalau:* halaman Skuad menampilkan konflik nyata dari dua feed, dan pilihan analis tersimpan.

**Tahap 2 · Halaman rujukan.** Skuad, Statistik, Berita. Ketiganya membaca data yang sudah ada, tanpa model. Bangun dulu karena paling sederhana dan langsung berguna. *Selesai kalau:* filter musim dan kompetisi di Statistik menghasilkan angka yang cocok dengan hitungan manual dari data laga.

**Tahap 3 · Metrik dan model turunan.** xG bisa diambil dari sumber, tapi xT, PPDA, bola kedua, beban 14 hari, dan nilai pemain dihitung sendiri. Semua rumus ada di `Inventaris Card.dc.html`. Tulis sebagai fungsi murni dengan tes, bukan query yang tersebar di UI. *Selesai kalau:* satu laga lama bisa dihitung ulang dan hasilnya sama setiap kali.

**Tahap 4 · Pasca laga.** Angka penentu, nilai pemain, laporan, saved moments, generator prompt. Bangun sebelum Live karena datanya diam, jadi lebih mudah diuji. *Selesai kalau:* laporan satu laga lama bisa dihasilkan tanpa campur tangan manual, dan prompt yang disalin menghasilkan konten yang angkanya persis sama dengan data.

**Tahap 5 · Pra laga.** Prediksi susunan, hipotesis taktik, head to head, pemain kunci, profil lawan, fakta pendukung. Wajib: simpan tiap prediksi dan hipotesis dengan cap waktu sebelum kick-off. *Selesai kalau:* prediksi untuk laga yang sudah berlangsung bisa diambil kembali beserta waktu pembuatannya.

**Tahap 6 · Live.** Detektor kartu pundit, lapangan, Game Highlights beserta dialog buktinya, dialog pemain, saved moments, kandidat rotasi, panel jeda, dan cek prediksi. Dikerjakan terakhir karena bergantung pada semua tahap sebelumnya. *Selesai kalau:* satu laga lama bisa diputar ulang dari event tersimpan dan menghasilkan urutan kartu yang sama seperti seharusnya muncul saat laga berjalan.

Catatan: **bangun mode putar ulang lebih dulu daripada mode langsung.** Menguji panel live dengan menunggu pertandingan berikutnya adalah cara paling lambat untuk mengembangkan app ini.

---

## Prompt Pembuka untuk Claude Code

Tempel ini di Claude Code setelah folder handoff ada di dalam repo:

```
Baca design_handoff_mu_analytics/README.md, lalu Inventaris Card.dc.html di folder yang sama —
itu spesifikasi logika tiap card, lengkap dengan rumus datanya. Panduan Console.dc.html berisi
alasan tiap panel ada. MU Analytics Console.dc.html adalah prototipe visual: ambil struktur,
hierarki, dan tokennya, jangan salin arsitekturnya.

Aku mau mulai dari Tahap 0 dan 1 di bagian Urutan Bangun. Sebelum menulis kode:
1. Usulkan skema database untuk semua entitas di bagian Data & Sumber, termasuk player_source_map.
2. Usulkan struktur folder dan pilihan library, dengan alasan singkat per pilihan.
3. Sebutkan keputusan yang masih perlu aku ambil dan tidak boleh kamu tebak.

Batasan yang tidak boleh dilanggar:
- Bahasa antarmuka Indonesia, istilah teknis sepak bola tetap dalam bentuk aslinya.
- Setiap angka yang ditampilkan harus bisa dilacak ke sumbernya.
- Jangan menambahkan fitur yang mengklaim sesuatu yang tidak bisa dilacak sistem
  (approval, "sudah diposting", "diperiksa oleh X").
- Skor selalu menulis Manchester United lebih dulu.
- Tidak ada lambang klub, foto pemain, atau aset pihak ketiga.
```

Setelah Tahap 0 dan 1 selesai, minta Claude Code mengerjakan satu tahap per sesi dan tutup tiap sesi dengan syarat selesai yang tertulis di atas.
