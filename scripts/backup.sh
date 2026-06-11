#!/usr/bin/env bash
#
# backup.sh — Example backup script.
# Archives the given source directory as a tar.gz into the destination directory.
# Returns exit 0 on success, != 0 on error (the scheduler counts it as "Failed").
#
set -euo pipefail

# --- Configuration (can be overridden via env) ---
SOURCE_DIR="${BACKUP_SOURCE:-/tmp/demo_data}"
DEST_DIR="${BACKUP_DEST:-/tmp/demo_backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

timestamp="$(date +%Y%m%d_%H%M%S)"
archive="${DEST_DIR}/backup_${timestamp}.tar.gz"

echo "[$(date '+%F %T')] Backup started"
echo "  Source : ${SOURCE_DIR}"
echo "  Target : ${archive}"

# If the source is missing, generate demo data (for example purposes).
if [[ ! -d "${SOURCE_DIR}" ]]; then
    echo "  Source directory missing, creating demo data..."
    mkdir -p "${SOURCE_DIR}"
    echo "demo content $(date)" > "${SOURCE_DIR}/sample.txt"
fi

mkdir -p "${DEST_DIR}"

# Archive it.
if tar -czf "${archive}" -C "${SOURCE_DIR}" . ; then
    size="$(du -h "${archive}" | cut -f1)"
    echo "[$(date '+%F %T')] Archive created (${size})"
else
    echo "ERROR: failed to create tar archive" >&2
    exit 1
fi

# Clean up old backups.
echo "  Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${DEST_DIR}" -name 'backup_*.tar.gz' -type f -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date '+%F %T')] Backup completed successfully"
exit 0
