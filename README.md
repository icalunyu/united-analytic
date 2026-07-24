# MU Analytics WebApp

Web app internal buat divisi analisis IndoManUtd Jogja. Detail konteks & scope lengkap ada di [projectbrief.md](projectbrief.md).

## Struktur repo

```
backend/    Django + DRF (API, models, ingestion command)
frontend/   React (Vite) — konsumsi REST API backend
```

## Jalanin di lokal

### Backend (Django + SQLite)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example backend/.env
# edit backend/.env: isi API_FOOTBALL_KEY (daftar gratis di api-sports.io atau RapidAPI)
# DB_ENGINE dibiarkan kosong supaya pakai SQLite

cd backend
python manage.py migrate
python manage.py createsuperuser   # opsional, buat akses /admin/
python manage.py runserver
```

Backend jalan di `http://localhost:8000`. Django admin di `http://localhost:8000/admin/`.

Narik jadwal MU dari API-Football:

```bash
python manage.py pull_fixtures                 # default: musim berjalan
python manage.py pull_fixtures --season 2024    # musim tertentu
```

> **Catatan free tier API-Football**: plan gratis cuma bisa akses musim 2022–2024 dan tidak mendukung parameter `next`/`last`. Musim yang sedang berjalan baru bisa ditarik kalau upgrade plan.

### Frontend (React + Vite)

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL default sudah pas buat dev lokal
npm run dev
```

Frontend jalan di `http://localhost:5173`, fetch data dari backend di `http://localhost:8000`.

## API endpoints

| Method | Path | Keterangan |
|---|---|---|
| GET | `/api/matches/` | Jadwal MU berikutnya. Query: `?season=`, `?all=true` |
| GET | `/api/matches/<id>/` | Detail 1 match + event |

## Deploy ke cPanel (production)

1. **Database**: bikin database PostgreSQL via cPanel → "PostgreSQL Databases", catat nama DB/user/password.
2. **Setup Python App** (cPanel) → arahkan ke folder `backend/`, install dependencies dari `requirements.txt`.
3. Bikin `backend/.env` langsung di server (jangan pernah commit file ini) isi:
   - `DJANGO_SECRET_KEY` — generate baru, jangan pakai punya dev
   - `DJANGO_DEBUG=False`
   - `DJANGO_ALLOWED_HOSTS=musafar.web.id`
   - `DB_ENGINE=postgres` + `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` sesuai database cPanel
   - `CORS_ALLOWED_ORIGINS=https://musafar.web.id`
   - `API_FOOTBALL_KEY`
4. Jalankan lewat terminal cPanel (di dalam virtualenv Python App):
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```
5. **Cron Job** (cPanel) — jadwalkan `pull_fixtures` berkala (misal tiap 30 menit saat matchday, atau harian di luar matchday) supaya hemat kuota API:
   ```bash
   /path/to/venv/bin/python /path/to/backend/manage.py pull_fixtures
   ```
6. **Frontend**: build static bundle, upload isi `frontend/dist/` ke `public_html` (atau subfolder-nya):
   ```bash
   cd frontend
   npm run build
   ```
   Set `VITE_API_BASE_URL` ke domain API production sebelum build (lewat `frontend/.env` lokal saat build, bukan runtime — Vite meng-inline env var saat build).

## Kredensial

Semua API key & DB password diisi manual lewat file `.env` di masing-masing environment (lokal/server) — tidak pernah di-hardcode di kode atau diminta lewat chat/AI.
