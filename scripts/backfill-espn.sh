#!/bin/bash
# Backfill sekali-jalan: tarik play-by-play ESPN buat musim-musim lama.
#
# Kenapa perlu: kurva momentum dihitung live di view dari MatchPlay, jadi laga
# tanpa play-by-play nggak punya kurva sama sekali. Waktu skrip ini dibikin,
# musim 2019-2024 kosong total — cuma 45 laga MU yang punya momentum.
#
# Jeda antar musim itu bukan basa-basi: ESPN nolak koneksi (connection reset,
# read timeout) kalau ditembak beruntun. Lihat logs/cron.log.
#
# WAJIB dikerjain sesudahnya, bukan opsional:
#   python manage.py pull_squad        # backfill bikin pemain historis lahir
#                                      # dengan is_active default; tanpa ini
#                                      # skuad MU melonjak 38 -> 79
#   python manage.py merge_duplicates  # dry run dulu, BACA barisnya
#   python manage.py merge_duplicates --apply
#
# Sekali jalan. Jangan masukin cron.

set -euo pipefail

APP_ROOT="${APP_ROOT:-$HOME/mu-analytics}"
PYTHON="${PYTHON:-$HOME/virtualenv/mu-analytics/3.11/bin/python}"
SEASONS="${SEASONS:-2023 2022 2021 2020 2019}"
JEDA="${JEDA:-20}"

cd "$APP_ROOT"

for S in $SEASONS; do
    echo "=================== MUSIM $S ==================="
    # --refresh WAJIB di sini. Sejak penyaring inkremental dipasang,
    # pull_match_events_espn melewati laga yang udah selesai & pernah ditarik —
    # tanpa flag ini skrip backfill exit 0 sambil nggak ngerjain apa-apa.
    "$PYTHON" manage.py pull_match_events_espn --season "$S" --refresh 2>&1 \
        | grep -E "fixture|Selesai|gagal|dilewati"
    sleep "$JEDA"
done

echo "=================== BACKFILL SELESAI ==================="
echo "Sekarang jalanin: pull_squad, lalu merge_duplicates (dry run dulu)."
