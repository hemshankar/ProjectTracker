#!/usr/bin/env bash
# Daily backup of the accounting ledger (the only irreplaceable accounting data).
# usage_daily rollups are rebuilt from the ledger, so they are not dumped.
#
#   scripts/accounting-backup.sh                      # dump into ./backups/accounting
#   BACKUP_COPY_CMD='aws s3 cp "$FILE" s3://bucket/accounting/' scripts/accounting-backup.sh
#
# Env (all optional):
#   MONGODUMP_CMD    how to run mongodump (default: inside the compose mongo container)
#   MONGO_DB         database to dump (default scatterboard_accounting)
#   BACKUP_DIR       local directory (default ./backups/accounting)
#   BACKUP_KEEP      local archives to keep (default 14)
#   BACKUP_COPY_CMD  off-host copy; runs with $FILE set. Failure fails the job.
set -euo pipefail

MONGODUMP_CMD="${MONGODUMP_CMD:-docker compose exec -T mongo mongodump}"
MONGO_DB="${MONGO_DB:-scatterboard_accounting}"
BACKUP_DIR="${BACKUP_DIR:-./backups/accounting}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/usage_ledger-$(date -u +%Y%m%dT%H%M%SZ).archive.gz"
trap 'rm -f "$FILE.partial"' EXIT

# --archive to stdout, written under a temp name so a failed dump never looks like a good backup.
$MONGODUMP_CMD --db "$MONGO_DB" --collection usage_ledger --gzip --archive > "$FILE.partial"
[ -s "$FILE.partial" ] || { echo "backup failed: empty dump" >&2; exit 1; }
mv "$FILE.partial" "$FILE"
echo "wrote $FILE ($(wc -c < "$FILE") bytes)"

if [ -n "${BACKUP_COPY_CMD:-}" ]; then
  export FILE
  bash -c "$BACKUP_COPY_CMD"
  echo "copied off-host"
else
  echo "WARNING: BACKUP_COPY_CMD not set; this backup exists only on this host" >&2
fi

# prune: keep the newest $BACKUP_KEEP archives
ls -1t "$BACKUP_DIR"/usage_ledger-*.archive.gz | tail -n +"$((BACKUP_KEEP + 1))" | xargs -I{} rm -f {}
