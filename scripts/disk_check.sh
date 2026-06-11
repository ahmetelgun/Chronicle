#!/usr/bin/env bash
#
# disk_check.sh — Disk usage check.
# If the root filesystem usage percentage exceeds the threshold, returns exit 2 (Failed);
# this makes the scheduler trigger a notification (Slack/Teams).
#
set -euo pipefail

THRESHOLD="${DISK_THRESHOLD:-90}"   # percent

echo "[$(date '+%F %T')] Disk check (threshold: ${THRESHOLD}%)"

# Get the root partition usage percentage (strip the % sign).
usage="$(df -P / | awk 'NR==2 {gsub("%",""); print $5}')"

echo "  / usage: ${usage}%"

if (( usage >= THRESHOLD )); then
    echo "WARNING: Disk usage exceeded the threshold (${usage}% >= ${THRESHOLD}%)" >&2
    echo "  Top 5 largest directories:" >&2
    du -sh /* 2>/dev/null | sort -rh | head -5 >&2 || true
    exit 2
fi

echo "[$(date '+%F %T')] Disk usage within normal limits"
exit 0
