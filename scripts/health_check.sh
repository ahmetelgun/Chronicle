#!/usr/bin/env bash
#
# health_check.sh — HTTP service health check.
# Sends a request to the given URL; if not HTTP 2xx/3xx, returns exit 2 (Failed).
#
set -euo pipefail

URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/}"
TIMEOUT="${HEALTHCHECK_TIMEOUT:-10}"

echo "[$(date '+%F %T')] Health check: ${URL}"

# If curl is missing, give a meaningful error.
if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: 'curl' not found" >&2
    exit 1
fi

http_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "${TIMEOUT}" "${URL}" || echo '000')"
echo "  HTTP status code: ${http_code}"

if [[ "${http_code}" =~ ^[23][0-9][0-9]$ ]]; then
    echo "[$(date '+%F %T')] Service healthy"
    exit 0
fi

echo "ERROR: Service unhealthy (HTTP ${http_code})" >&2
exit 2
