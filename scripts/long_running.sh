#!/usr/bin/env bash
#
# long_running.sh — For testing the timeout mechanism.
# Runs for a long time; set the Job's timeout_seconds to a small value (e.g. 5s)
# and observe the scheduler killing the process with SIGTERM ("Timeout").
#
set -euo pipefail

DURATION="${LONG_RUN_SECONDS:-120}"

echo "[$(date '+%F %T')] Long task started (will run for ${DURATION} s)"

# Clean exit message when SIGTERM is caught (the scheduler sends this).
trap 'echo "[$(date "+%F %T")] SIGTERM received, shutting down..." >&2; exit 143' TERM

for (( i=1; i<=DURATION; i++ )); do
    echo "  ... running (${i}/${DURATION})"
    sleep 1
done

echo "[$(date '+%F %T')] Long task completed"
exit 0
