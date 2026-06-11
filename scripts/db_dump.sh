#!/usr/bin/env bash
#
# db_dump.sh — Example database backup (PostgreSQL).
# Uses pg_dump in a real environment; in demo mode it simulates when the command is missing.
#
set -euo pipefail

DB_NAME="${PGDATABASE:-appdb}"
DB_USER="${PGUSER:-postgres}"
DEST_DIR="${DB_DUMP_DEST:-/tmp/demo_db_dumps}"

timestamp="$(date +%Y%m%d_%H%M%S)"
dump_file="${DEST_DIR}/${DB_NAME}_${timestamp}.sql.gz"

echo "[$(date '+%F %T')] DB backup started: ${DB_NAME}"
mkdir -p "${DEST_DIR}"

if command -v pg_dump >/dev/null 2>&1; then
    echo "  Backing up with pg_dump..."
    if pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip > "${dump_file}"; then
        echo "[$(date '+%F %T')] Backup taken: ${dump_file}"
    else
        echo "ERROR: pg_dump failed" >&2
        exit 1
    fi
else
    # Demo: if pg_dump is missing, generate a sample dump.
    echo "  (demo) pg_dump not found, generating a sample dump..."
    {
        echo "-- Demo DB dump @ $(date)"
        echo "-- database: ${DB_NAME}"
    } | gzip > "${dump_file}"
    echo "[$(date '+%F %T')] Demo backup created: ${dump_file}"
fi

exit 0
