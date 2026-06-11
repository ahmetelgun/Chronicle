#!/usr/bin/env bash
#
# random_fail.sh — For testing the notification (Slack/Teams) system.
# Returns exit 1 (Failed) with 50% probability; this triggers the webhook alert.
#
set -euo pipefail

echo "[$(date '+%F %T')] Task started (random outcome test)"
sleep 1

# Random between 0 and 1.
if (( RANDOM % 2 == 0 )); then
    echo "[$(date '+%F %T')] Task succeeded"
    exit 0
else
    echo "ERROR: Simulated critical failure — task aborted" >&2
    echo "Stack trace (example):" >&2
    echo "  at module.process (line 42)" >&2
    echo "  at main (line 10)" >&2
    exit 1
fi
