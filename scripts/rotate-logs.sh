#!/bin/bash
# Rotasi cron.log — shared hosting ini nggak punya logrotate buat user biasa,
# jadi dikerjain manual lewat cron.
#
# Semua job cron nulis append ke satu file tanpa batas; dibiarin, dia numbuh
# terus sampai makan kuota disk.
#
# Dipasang di crontab:
#   50 3 * * * /home/musafarw/mu-analytics/scripts/rotate-logs.sh

set -eu

LOG_DIR="${LOG_DIR:-$HOME/mu-analytics/logs}"
LOG="$LOG_DIR/cron.log"
MAX_BYTES="${MAX_BYTES:-1048576}"   # 1 MB
KEEP=3                              # jumlah arsip .gz yang disimpen

[ -f "$LOG" ] || exit 0
[ "$(wc -c < "$LOG")" -gt "$MAX_BYTES" ] || exit 0

# Geser arsip lama: .2.gz -> .3.gz, .1.gz -> .2.gz, dst.
rm -f "$LOG.$KEEP.gz"
i=$((KEEP - 1))
while [ "$i" -ge 1 ]; do
    [ -f "$LOG.$i.gz" ] && mv "$LOG.$i.gz" "$LOG.$((i + 1)).gz"
    i=$((i - 1))
done

# Disalin lalu dikosongin DI TEMPAT, bukan di-mv. Job cron yang kebetulan
# lagi jalan masih megang file descriptor ke inode ini — kalau file-nya
# dipindah, output-nya bakal masuk ke arsip dan hilang dari log aktif.
cp "$LOG" "$LOG.1"
: > "$LOG"
gzip -f "$LOG.1"

echo "$(date '+%Y-%m-%d %H:%M:%S') rotate-logs: cron.log dirotasi" >> "$LOG"
