# MU Analytics WebApp — Project Brief

## Konteks
Aku pengurus komunitas fans Manchester United "IndoManUtd" regional Jogja. Aku mau bikin divisi analisis baru (belum ada di regional manapun) dan butuh web app internal buat mendukungnya dengan data.

## Tujuan (Jobs To Be Done)
Sebagai analis, aku pengen bisa:
1. **Live pundit saat match** — commentary berbasis data real-time sambil nonton
2. **Post-match summary** — bahan konten untuk tim socmed IndoManUtd Jogja
3. **Pre-match prediksi taktik & formasi** — bahan konten sebelum pertandingan
4. **Analisis kebutuhan transfer** — posisi mana yang perlu diperkuat (CB, RB/LB, ATM, CM, CDM, CF, winger) berdasarkan data performa skuad
5. **Evaluasi transfer window** — analisis pemain yang direkrut MU setelah bursa transfer tutup

Data yang relevan: berita, pre/during/post match, rumor & realisasi transfer, pemain masuk/keluar, pemain on loan (dari/ke MU), berita fans, jadwal, cedera/fit, statistik pemain (menit main, gol, asis, short/long pass, intercept, saves untuk kiper), dll.

## Tech Stack (sudah difinalkan)
| Layer | Pilihan |
|---|---|
| Backend | Django + Django REST Framework |
| Database (dev) | SQLite (default Django) |
| Database (production) | PostgreSQL (tersedia di cPanel DomaiNesia) |
| Deploy backend | cPanel "Setup Python App" (Passenger WSGI) |
| Data ingestion | Django management commands, dijalankan berkala via Cron Job cPanel |
| Frontend | React (Vite), di-build jadi static files, di-upload ke `public_html`, konsumsi Django REST API |
| Data source awal | API-Football (api-sports.io / RapidAPI) — mulai dari free tier |

### Kenapa stack ini
- Shared hosting cPanel **tidak mendukung proses yang jalan terus-menerus** (no persistent Node server, no Celery/Redis worker, no WebSocket server) — makanya data ingestion pakai Cron Job + management command, bukan background worker, dan "live update" di frontend pakai polling ke REST API (bukan WebSocket).
- Frontend React di-build sebagai static bundle supaya tidak butuh proses Node yang jalan di server — cukup file statis.
- Postgres dipilih di atas MySQL karena didukung penuh oleh hosting ini dan lebih kuat untuk data terstruktur/JSON dari API eksternal.

## Hosting target (production)
- cPanel-based shared hosting (DomaiNesia), domain: musafar.web.id
- Tersedia: Setup Python App, PostgreSQL Databases, Cron Jobs, File Manager
- Kredensial (API key, DB password) akan diisi manual oleh saya di file `.env` di server — jangan pernah minta atau hardcode kredensial ini di kode/chat.

## Scope Fase 1 (mulai dari sini)
1. Setup project Django (REST framework, struktur app `matches`, `players`, `transfers`)
2. Models dasar: `Team`, `Player`, `Match`, `MatchEvent`, `Injury`
3. Integrasi API-Football: service/client buat fetch fixtures & data pertandingan
4. Management command `pull_fixtures` — narik jadwal & simpan/update ke database
5. REST endpoint: list jadwal pertandingan MU berikutnya + detail match
6. Frontend React sederhana: halaman nampilin jadwal MU berikutnya, ambil data dari endpoint di atas
7. `.env.example` dengan semua environment variable yang dibutuhkan (API key, DB credentials, secret key) — TANPA nilai asli
8. README singkat: cara jalanin di lokal (SQLite) dan catatan deploy ke cPanel (Postgres)

## Fase berikutnya (belum dikerjakan sekarang, cukup diketahui sebagai arah)
- Fase 2: live match dashboard (polling event, buat live pundit)
- Fase 3: post-match summary generator
- Fase 4: cedera & pre-match taktik dashboard
- Fase 5: transfer tracker (kurasi manual rumor via RSS + market value dari Transfermarkt unofficial API)

## Catatan penting
- API-Football free tier terbatas (100 request/hari) — desain ingestion supaya hemat kuota: cron narik data lalu simpan ke DB, semua request dari user dilayani dari DB, bukan hit API langsung tiap kali ada visitor.
- Jangan pernah scraping Flashscore — ToS mereka melarang eksplisit.
- Untuk rumor transfer/Twitter: TIDAK pakai API X resmi (mahal sejak 2026, pay-per-use). Sumber awal: RSS feed media bola (BBC Sport, Sky Sports, Manchester Evening News, situs resmi MU) + kurasi manual oleh tim analis.
