#!/usr/bin/env bash
#
# cleanup_temp.sh — Temporary file cleanup.
# Deletes files older than N days in the given directory and writes a summary report.
#
set -euo pipefail

TARGET_DIR="${CLEANUP_DIR:-/tmp}"
AGE_DAYS="${CLEANUP_AGE_DAYS:-3}"
PATTERN="${CLEANUP_PATTERN:-*.tmp}"

echo "[$(date '+%F %T')] Cleanup started"
echo "  Directory : ${TARGET_DIR}"
echo "  Pattern   : ${PATTERN} (>${AGE_DAYS} days)"

if [[ ! -d "${TARGET_DIR}" ]]; then
    echo "ERROR: Target directory not found: ${TARGET_DIR}" >&2
    exit 1
fi

# Count what will be deleted, then delete.
count="$(find "${TARGET_DIR}" -maxdepth 1 -name "${PATTERN}" -type f -mtime "+${AGE_DAYS}" 2>/dev/null | wc -l | tr -d ' ')"
find "${TARGET_DIR}" -maxdepth 1 -name "${PATTERN}" -type f -mtime "+${AGE_DAYS}" -delete 2>/dev/null || true

echo "[$(date '+%F %T')] ${count} files cleaned up"
exit 0
