#!/bin/bash
# Backup Postgres harian, disalin ke Google Drive lewat rclone.
#
# Kenapa ada: sebelum ini semua dump menumpuk di ~/mu-analytics/ — server yang
# SAMA dengan Postgres-nya, dan semuanya dibuat manual. Satu akun hosting
# hilang, hilang juga backfill 8 musim; menariknya ulang butuh ~1.900 panggilan
# ke API ESPN yang tidak resmi.
#
# Kredensial DB dibaca dari .env, TIDAK pernah ditulis di skrip ini.
# Token Google ada di ~/.config/rclone/rclone.conf (mode 600) dan dibuat lewat
# `rclone config` oleh pemilik akun — bukan oleh skrip ini.
#
# Dipasang di crontab:
#   30 3 * * * /home/musafarw/mu-analytics/scripts/backup-db.sh >> /home/musafarw/mu-analytics/logs/cron.log 2>&1

set -euo pipefail

APP_ROOT="${APP_ROOT:-$HOME/mu-analytics}"
RCLONE="${RCLONE:-$HOME/bin/rclone}"
REMOTE="${REMOTE:-gdrive:mu-analytics-backup}"
SIMPAN_LOKAL="${SIMPAN_LOKAL:-3}"    # dump .dump yang ditahan di server
SIMPAN_REMOTE="${SIMPAN_REMOTE:-14}" # hari retensi di Drive

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') backup-db: $*"; }

cd "$APP_ROOT"

if [ ! -f .env ]; then
    log "GAGAL: .env tidak ada di $APP_ROOT"
    exit 1
fi

# Ambil hanya variabel DB_*, jangan seluruh .env — di sana ada API key provider
# yang tidak ada urusannya dengan pg_dump.
#
# Dibaca baris per baris, BUKAN pakai `eval` atau `source`. Password produksi
# mengandung karakter khusus; `eval` sempat memperlakukan potongannya sebagai
# nama variabel dan skripnya mati dengan "unbound variable" sambil MENCETAK
# potongan password itu ke log. `printf -v` menugaskan nilai tanpa pernah
# menafsirkannya sebagai kode.
#
# Dibaca langsung `< .env`, bukan `< <(grep ...)`: host ini tidak menyediakan
# /dev/fd, jadi process substitution mati dengan "No such file or directory".
# Penyaringannya dikerjakan `case` di dalam loop.
DB_NAME=""; DB_USER=""; DB_PASSWORD=""; DB_HOST=""; DB_PORT=""
while IFS='=' read -r kunci nilai; do
    # Buang kutip pembungkus kalau ada (.env boleh ditulis DB_PASSWORD="...").
    case "$nilai" in
        \"*\") nilai="${nilai#\"}"; nilai="${nilai%\"}" ;;
        \'*\') nilai="${nilai#\'}"; nilai="${nilai%\'}" ;;
    esac
    case "$kunci" in
        DB_NAME|DB_USER|DB_PASSWORD|DB_HOST|DB_PORT) printf -v "$kunci" '%s' "$nilai" ;;
    esac
done < .env

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ]; then
    log "GAGAL: DB_NAME/DB_USER/DB_PASSWORD tidak terbaca dari .env"
    exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
NAMA="mu-analytics-${STAMP}.dump"
TUJUAN="$APP_ROOT/backups/$NAMA"
mkdir -p "$APP_ROOT/backups"

log "mulai dump -> $NAMA"
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" \
    -U "$DB_USER" -Fc "$DB_NAME" -f "$TUJUAN"

UKURAN=$(stat -c %s "$TUJUAN")
if [ "$UKURAN" -lt 1000000 ]; then
    # Dump yang tiba-tiba mungil itu gejala dump yang gagal separuh jalan.
    # Lebih baik berisik sekarang daripada ketahuan pas butuh restore.
    log "GAGAL: dump cuma $UKURAN byte, terlalu kecil — tidak diunggah"
    exit 1
fi
log "dump selesai, $((UKURAN / 1024 / 1024)) MB"

# --- Rotasi lokal dikerjakan DULU, sebelum urusan Drive ---------------------
# Sengaja di sini, bukan di akhir: kalau Drive belum tersambung (atau lagi
# error), skrip ini berhenti sebelum sempat merotasi. Dump 16 MB per hari akan
# menumpuk diam-diam sampai kuota hosting habis. Rotasi lokal tidak bergantung
# pada remote, jadi tidak ada alasan menundanya.
log "rotasi lokal: sisakan ${SIMPAN_LOKAL} dump terbaru"
ls -1t "$APP_ROOT/backups"/mu-analytics-*.dump 2>/dev/null \
    | tail -n +$((SIMPAN_LOKAL + 1)) \
    | while read -r tua; do
        log "  hapus lokal $(basename "$tua")"
        rm -f "$tua"
    done

# --- Salinan off-server -----------------------------------------------------
if [ ! -x "$RCLONE" ]; then
    log "PERINGATAN: rclone tidak ada di $RCLONE — dump tersimpan LOKAL SAJA"
    exit 1
fi

if ! "$RCLONE" listremotes 2>/dev/null | grep -q "^${REMOTE%%:*}:"; then
    log "PERINGATAN: remote '${REMOTE%%:*}' belum dikonfigurasi."
    log "  Jalankan '~/bin/rclone config' buat menyambungkan Google Drive."
    log "  Dump harian tetap jalan dan berotasi, TAPI masih di server yang sama"
    log "  dengan Postgres-nya — belum ada salinan off-server."
    exit 1
fi

log "unggah ke $REMOTE"
"$RCLONE" copy "$TUJUAN" "$REMOTE" --transfers 1 --retries 3 --low-level-retries 5

# Pastikan benar-benar sampai. `rclone copy` bisa sukses tanpa file di tujuan
# kalau remote-nya salah arah — verifikasi lebih murah daripada percaya.
if "$RCLONE" lsf "$REMOTE/$NAMA" >/dev/null 2>&1; then
    log "terverifikasi ada di Drive: $NAMA"
else
    log "GAGAL: $NAMA tidak ketemu di $REMOTE sesudah unggah"
    exit 1
fi

log "rotasi remote: buang yang lebih tua dari ${SIMPAN_REMOTE} hari"
"$RCLONE" delete "$REMOTE" --min-age "${SIMPAN_REMOTE}d" || log "PERINGATAN: rotasi remote gagal"

SISA=$("$RCLONE" lsf "$REMOTE" 2>/dev/null | wc -l)
LOKAL=$(ls -1 "$APP_ROOT/backups"/*.dump 2>/dev/null | wc -l)
log "selesai. $SISA salinan di Drive, $LOKAL di server"
