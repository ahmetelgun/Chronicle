# job_logger.sh — Logging helper for Bash scripts (Job Scheduler format).
#
# Usage:
#   source /path/to/job_logger.sh
#   jl_init                  # writes header, automatic footer on EXIT
#   jl_info "started"
#   jl_event email "To: a@b.com | subject: Report"
#   jl_metric emails_sent 42
#   jl_warn "smtp retry"
#   jl_error "delivery error"    # sets status to FAILED
#
# Log file: <script_dir>/logs/<script_stem>-<YYYYmmddHHMMSS_UTC>.log
# Times are UTC. (Second precision; .000 is written as milliseconds.)
# NOTE: RAM/CPU is not measured in bash; these fields stay '-' (the Python job_logger measures them).

_JL_FILE=""
_JL_STATUS="SUCCESS"
declare -A _JL_EVENTS
declare -A _JL_METRICS

_jl_ts() { date -u +"%Y-%m-%d %H:%M:%S.000"; }

jl_init() {
    local script_path stem dir
    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    stem="$(basename "$0")"; stem="${stem%.*}"
    dir="$(dirname "$script_path")/logs"
    mkdir -p "$dir"
    _JL_FILE="$dir/${stem}-$(date -u +%Y%m%d%H%M%S)-$$.log"
    {
        echo "# ===================== EXECUTION LOG (UTC) ====================="
        echo "# job:        ${JOB_NAME:-$stem}"
        echo "# script:     $script_path"
        echo "# cwd:        $(pwd)"
        echo "# trigger:    ${JOB_TRIGGER:-INDEPENDENT}"
        echo "# user:       ${JOB_USER:-$(whoami)}"
        echo "# pid:        $$"
        echo "# started:    $(_jl_ts)"
        echo "# =============================================================="
    } > "$_JL_FILE"
    _JL_START="$(date -u +%s)"
    trap 'jl_close' EXIT
    trap 'jl_close TIMEOUT; exit 143' TERM
}

_jl_line() { printf '%s  %-7s %s\n' "$(_jl_ts)" "$1" "$2" >> "$_JL_FILE"; }

jl_out()   { _jl_line "OUT" "$1"; }
jl_info()  { _jl_line "INFO" "$1"; }
jl_warn()  { _jl_line "WARN" "$1"; _JL_EVENTS[warning]=$(( ${_JL_EVENTS[warning]:-0} + 1 )); }
jl_error() { _jl_line "ERROR" "$1"; _JL_EVENTS[error]=$(( ${_JL_EVENTS[error]:-0} + 1 )); }
jl_event() {
    local cat="$1"; shift
    _jl_line "EVENT" "[$cat] $*"
    _JL_EVENTS[$cat]=$(( ${_JL_EVENTS[$cat]:-0} + 1 ))
}
jl_metric() {
    _jl_line "METRIC" "$1=$2"
    _JL_METRICS[$1]=$(( ${_JL_METRICS[$1]:-0} + ${2%.*} ))
}

# Custom header field — call it RIGHT after jl_init (written to the header block).
jl_header() { echo "# $1: $2" >> "$_JL_FILE"; }
# Custom footer field — written in jl_close.
declare -A _JL_FOOTER
jl_footer() { _JL_FOOTER[$1]="$2"; }

jl_close() {
    [ -z "$_JL_FILE" ] && return
    local status="${1:-$_JL_STATUS}" ev="" mt="" k dur
    dur=$(( $(date -u +%s) - ${_JL_START:-0} ))
    for k in "${!_JL_EVENTS[@]}"; do ev="$ev $k=${_JL_EVENTS[$k]}"; done
    for k in "${!_JL_METRICS[@]}"; do mt="$mt $k=${_JL_METRICS[$k]}"; done
    {
        echo "# --------------------------------------------------------------"
        echo "# status:           $status"
        echo "# exit_code:        $([ "$status" = SUCCESS ] && echo 0 || echo 1)"
        echo "# finished:         $(_jl_ts)"
        echo "# duration_sec:     $dur"
        echo "# cpu_time_sec:     -"
        echo "# cpu_pct:          -"
        echo "# max_rss_mb:       -"
        echo "# summary_events:  ${ev:- -}"
        echo "# summary_metrics: ${mt:- -}"
        for k in "${!_JL_FOOTER[@]}"; do echo "# $k: ${_JL_FOOTER[$k]}"; done
        echo "# =============================================================="
    } >> "$_JL_FILE"
    _JL_FILE=""  # prevent closing again
}
