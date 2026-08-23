# MU Analytics WebApp

Web app internal buat divisi analisis IndoManUtd Jogja. Detail konteks & scope lengkap ada di [projectbrief.md](projectbrief.md).

Riwayat perubahan besar di lapisan data — beserta keputusan, jebakan, dan
batas yang sudah teruji — ada di [CATATAN-PERUBAHAN-BESAR.md](CATATAN-PERUBAHAN-BESAR.md).
Baca itu dulu sebelum menyentuh sistem dedup, provenance, atau ingestion.

Satu server Django — backend (Django REST Framework, buat integrasi lain kalau perlu) dan frontend (Django templates + Tailwind CSS + Chart.js) jalan di port yang sama, nggak ada proses Node terpisah.

## Struktur repo

```
backend/
  config/       settings, urls
  matches/      model Match/MatchEvent/MatchTeamStatistics, REST API, semua management command pull_*
  players/      model Team/Player/Injury, REST API, sistem dedup lintas provider
  dashboard/    views + templates (Django templates, bukan SPA) — halaman yang beneran dilihat user
  static_src/   source CSS Tailwind (input.css)
  static/       hasil compile Tailwind (tailwind.css) — di-commit, server nggak perlu Node
```

## Jalanin di lokal

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example backend/.env
# edit backend/.env: isi API key provider yang mau dipake (lihat bagian "Sumber data" di bawah)
# DB_ENGINE dibiarkan kosong supaya pakai SQLite

cd backend
python manage.py migrate
python manage.py createsuperuser   # opsional, buat akses /admin/
python manage.py runserver
```

Buka `http://localhost:8000/` — itu udah halaman Dashboard-nya. Django admin di `/admin/`.

### Kalau ubah template/styling (Tailwind)

Tailwind CLI standalone udah didownload ke `backend/tailwindcss` (nggak di-commit ke git, binary besar & platform-specific). Kalau belum ada:

```bash
cd backend
curl -sL "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64" -o tailwindcss
chmod +x tailwindcss
```
(Ganti `macos-arm64` sesuai OS kalau bukan Mac Apple Silicon — cek [rilis Tailwind](https://github.com/tailwindlabs/tailwindcss/releases/latest).)

Compile ulang tiap habis ubah class Tailwind di template:
```bash
./tailwindcss -i static_src/input.css -o static/css/tailwind.css --minify
```

## Sumber data

Data ditarik dari 6 provider gratis yang saling melengkapi (kalau satu kena quota/limit, yang lain masih bisa jalan). Sistem dedup otomatis (`players/dedup.py`, `matches/dedup.py`) nyatuin data yang sama dari provider berbeda jadi 1 record.

| Command | Provider | Data |
|---|---|---|
| `pull_fixtures` | API-Football | Jadwal historis (free tier: musim 2022-2024 doang) |
| `pull_fixtures_fd` | football-data.org | Jadwal musim berjalan (Premier League + UCL) |
| `pull_fixtures_sdb` | TheSportsDB | Fallback jadwal, nggak butuh API key |
| `pull_squad` | football-data.org | Skuad MU |
| `pull_squad_sdb` | TheSportsDB | Fallback skuad + posisi lebih presisi |
| `pull_injuries` | Highlightly | Riwayat cedera |
| `pull_match_events` | Highlightly | Event pertandingan (quota harian ketat) |
| `pull_match_events_espn` | ESPN (API internal, tidak resmi) | Event + statistik pertandingan, cover 8 kompetisi (`--slug` buat pilih 1, atau semua sekaligus) |
| `pull_match_events_pl` | Premier League resmi (PulseLive/Opta) | Event pertandingan resmi, riwayat sejak 1992/93, cuma Premier League |
| `pull_xg_understat` | Understat | xG tiap tembakan + xG/xA/xGChain/xGBuildup & menit main per pemain. Cuma Premier League |
| `pull_fotmob` | FotMob | Statistik pemain terlengkap (aksi bertahan per pemain, touches, umpan ke sepertiga akhir), statistik tim dgn umpan per paruh, shotmap + xGOT, kurva momentum |

Isi API key yang mau dipake di `backend/.env` (lihat `.env.example` buat daftar lengkap variable + link daftar tiap provider).

### Apa yang ditarik dari ESPN

`pull_match_events_espn` itu command paling "gemuk" — sekali jalan dia nyimpen:

- **Event** (gol/kartu/substitusi) → `MatchEvent`, buat timeline
- **Seluruh play-by-play** (tembakan meleset, sepak pojok, pelanggaran, offside) berikut koordinat lapangan → `MatchPlay`, bahan mentah momentum serangan
- **28 statistik tim** (termasuk tekel, intersep, umpan silang, sapuan) → `MatchTeamStatistics`
- **Statistik per pemain per match** + formasi awal (mis. `4-2-3-1`) → `PlayerMatchStatistics`

Catatan penting buat yang mau ngoprek: ESPN ngirim play yang sama berkali-kali
di `commentary` dengan `sequence` beda-beda (96 entri bisa cuma 60 play unik),
jadi dedup **wajib** pakai `play.id`. Kalau nggak, pelanggaran kehitung dobel
dan momentumnya ngaco.

## Momentum serangan

Grafik momentum di halaman match dihitung sendiri (`matches/momentum.py`), bukan
diambil dari provider manapun. Alurnya: tiap play dikasih bobot bahaya
(gol > tembakan tepat sasaran > tembakan diblok > sepak pojok), dikali faktor
kedekatan ke gawang dari koordinat lapangan ESPN, lalu disebar ke beberapa menit
sekitarnya biar kurvanya halus. Nilainya bertanda — positif tuan rumah, negatif
tamu.

Alasan dihitung sendiri walaupun FotMob nyediain momentum jadi: FotMob cuma
ngasih momentum buat kompetisi resmi — laga persahabatan dapat `momentum: false`.
Model sendiri jalan di semua laga selama play-by-play ESPN-nya ada. FotMob
dipakai sebagai pembanding buat nyetel bobot, bukan sumber tampilan.

(Sofascore sempat dicoba buat peran itu dan ditinggalkan: endpoint mereka nolak
koneksi dari mana pun kita tes, lokal maupun server.)

Buat nyetel bobotnya ada `calibrate_momentum`. Dia bandingin kurva kita sama
momentum FotMob (yang disimpen `pull_fotmob`) dan ngitung korelasinya. Nggak
nyentuh jaringan — semua dibaca dari database:

```bash
python manage.py calibrate_momentum --all
```

Awalnya command ini nembak Sofascore, tapi endpoint mereka nolak koneksi dari
mana pun kita coba (lokal maupun server), jadi nggak pernah bisa dites. FotMob
ngasih data yang sama bentuknya dan bisa dijangkau.

Patokan sekarang: korelasi rata-rata **+0.44**. Di bawah 0.6, jadi masih ada
ruang setel di `PLAY_WEIGHTS` — bedanya sekarang hasil setelan itu keukur.

## Deploy ke cPanel (production)

Server ini (DomaiNesia, `musafar.web.id`) udah pernah dipakai buat deploy app Django lain, jadi polanya udah dikenal:

1. **Setup Python App** (cPanel UI, sekali doang) — bikin app slot baru, domain/subdomain sendiri (misal `api.musafar.web.id`), python 3.11. cPanel bakal generate venv + `.htaccess` otomatis di documentroot subdomain itu.
2. **Database PostgreSQL** (cPanel UI) — bikin database + user, catat kredensialnya.
3. **App root**: `~/mu-analytics`, dan `.htaccess` di documentroot diarahin ke situ lewat `PassengerAppRoot`.

   Perhatikan bentuknya — **isi folder `backend/` disalin rata ke app root**, jadi di server `manage.py`, `config/`, `matches/`, `dashboard/` ada di `~/mu-analytics/` langsung, tanpa lapisan `backend/`. Path repo `backend/config/settings.py` berarti `~/mu-analytics/config/settings.py` di server.
4. Environment variable (`DJANGO_SECRET_KEY`, `DB_*`, API key provider) diisi lewat file `.env` di app root (`~/mu-analytics/.env`, mode 600). `settings.py` baca `os.environ` lewat `python-dotenv`, jadi `SetEnv` di `.htaccess` juga jalan kalau lebih disuka.
5. Deploy sequence (tiap update):

   **Server ini nggak punya git repo** — `~/mu-analytics` bukan working copy, nggak ada `.git`. Deploy dilakukan dengan nyalin file. Jangan pakai `git pull` di sana: dia bakal gagal `fatal: not a git repository`, dan kalau outputnya dipipe (`git pull | tail`) exit code yang kebaca itu punya `tail`, jadi `set -e` pun lolos dan deploy-nya **kelihatan sukses padahal kode nggak berubah**.

   ```bash
   # dari root repo di lokal — perhatikan backend/ diratakan ke app root
   rsync -av --delete \
     --exclude '__pycache__' --exclude 'staticfiles' --exclude '.env' \
     --exclude 'db.sqlite3' --exclude 'tests.py' \
     -e 'ssh -p 64000' backend/ musafarw@sanremo.sg.rapidplex.com:~/mu-analytics/
   ```
   lalu di server:
   ```bash
   cd ~/mu-analytics
   ~/virtualenv/mu-analytics/3.11/bin/pip install -r requirements.txt --quiet
   ~/virtualenv/mu-analytics/3.11/bin/python manage.py migrate --noinput
   ~/virtualenv/mu-analytics/3.11/bin/python manage.py collectstatic --noinput
   touch tmp/restart.txt   # trigger restart Passenger — selalu paling akhir
   ```
   Selalu verifikasi kode yang di server benar-benar berubah (mis. `grep` baris yang baru), jangan percaya "deploy sukses" begitu saja.
6. **Cron Job** (cPanel) — jadwalkan `pull_fixtures_fd`/`pull_match_events_espn`/dkk berkala (tiap beberapa menit pas matchday, harian di luar itu) supaya data nggak statis dan hemat kuota API.

## Kredensial

Semua API key & DB password diisi manual lewat file `.env` (lokal) atau `SetEnv` di cPanel (server) — tidak pernah di-hardcode di kode atau diminta lewat chat/AI.
