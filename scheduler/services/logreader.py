"""
Log reading/scanning service — files are the source of truth.

Each run is a .log file in the logs/ folder of the script's directory.
This service scans those files, parses the header/footer, and produces "Run"
objects for the dashboard/listing. Runs outside the scheduler (independent ones)
also appear automatically, since their files are written to the same place.
"""
from __future__ import annotations

import base64
import datetime as _dt
import os
import re
from pathlib import Path

from django.conf import settings
from django.utils import timezone

# Body line: "YYYY-MM-DD HH:MM:SS.mmm  LEVEL    message"
_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(\w+)\s+(.*)$"
)
# Header/footer line: "# key: value" (key [a-z0-9_])
_KV_RE = re.compile(r"^#\s*([a-z0-9_]+):\s*(.*)$")

_HEADER_SCAN = 30   # number of lines to read from the start (room for custom header fields)
_FOOTER_BYTES = 4096  # bytes to read from the end (footer + custom fields)

# Built-in (reserved) field names — custom fields are anything outside this set.
_RESERVED_KEYS = {
    "job", "script", "cwd", "trigger", "user", "pid", "started",
    "status", "exit_code", "finished", "duration_sec", "cpu_time_sec",
    "cpu_pct", "max_rss_mb", "summary_events", "summary_metrics",
}


def _parse_utc(s: str):
    """'YYYY-MM-DD HH:MM:SS.mmm' (UTC) -> aware datetime."""
    try:
        naive = _dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S.%f")
        return naive.replace(tzinfo=_dt.UTC)
    except (ValueError, AttributeError):
        return None


def _parse_kv_summary(s: str) -> dict:
    """'email=18 warning=1' -> {'email': 18, 'warning': 1}. '-' -> {}."""
    out: dict[str, float] = {}
    if not s or s.strip() == "-":
        return out
    for tok in s.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            try:
                num = float(v)
                out[k] = int(num) if num.is_integer() else num
            except ValueError:
                continue
    return out


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class Run:
    """A run parsed from a single log file."""

    def __init__(self, path: Path, header: dict, footer: dict):
        self.path = path
        self.token = encode_token(path)
        self.job_name = header.get("job", path.stem)
        self.script = header.get("script", "")
        self.cwd = header.get("cwd", "")
        self.trigger = header.get("trigger", "INDEPENDENT")
        self.user = header.get("user", "-")
        self.pid = header.get("pid", "")
        self.started = _parse_utc(header.get("started", ""))

        finished_present = "status" in footer
        self.finished = _parse_utc(footer.get("finished", "")) if finished_present else None
        self.exit_code = footer.get("exit_code")
        self.duration_sec = _to_float(footer.get("duration_sec"))
        self.cpu_time_sec = _to_float(footer.get("cpu_time_sec"))
        self.cpu_pct = _to_float(footer.get("cpu_pct"))
        self.max_rss_mb = _to_float(footer.get("max_rss_mb"))
        self.event_summary = _parse_kv_summary(footer.get("summary_events", ""))
        self.metric_summary = _parse_kv_summary(footer.get("summary_metrics", ""))

        # Custom (non-reserved) header/footer fields.
        self.header_extra = {k: v for k, v in header.items() if k not in _RESERVED_KEYS}
        self.footer_extra = {k: v for k, v in footer.items() if k not in _RESERVED_KEYS}

        if finished_present:
            self.status = footer.get("status", "SUCCESS")
        elif _pid_alive(self.pid):
            self.status = "RUNNING"
        else:
            self.status = "ABORTED"  # no footer and the process is dead (kill/segfault)

    # --- helper views ---
    @property
    def is_running(self) -> bool:
        return self.status == "RUNNING"

    @property
    def is_failure(self) -> bool:
        return self.status in ("FAILED", "TIMEOUT", "ERROR", "ABORTED")

    @property
    def status_display(self) -> str:
        return {
            "SUCCESS": "Success", "FAILED": "Failed", "TIMEOUT": "Timeout",
            "ERROR": "System Error", "RUNNING": "Running", "ABORTED": "Aborted",
        }.get(self.status, self.status)

    @property
    def trigger_display(self) -> str:
        if self.trigger == "SCHEDULER":
            return "Scheduler (automatic)"
        if self.trigger == "INDEPENDENT":
            return f"Independent ({self.user})"
        return self.user  # MANUAL

    @property
    def warning_count(self) -> int:
        return int(self.event_summary.get("warning", 0))

    @property
    def error_count(self) -> int:
        return int(self.event_summary.get("error", 0))


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
#  Parsing
# ---------------------------------------------------------------------------
def _read_header(path: Path) -> dict:
    """Parses the leading '#' comment block (up to the first body line) as the header."""
    header = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for _ in range(_HEADER_SCAN):
            line = fh.readline()
            if not line:
                break
            s = line.rstrip("\n")
            if not s.startswith("#"):
                break  # body started, header ended
            m = _KV_RE.match(s)
            if m:
                header[m.group(1)] = m.group(2).strip()
    return header


def _read_footer(path: Path) -> dict:
    """Parses the trailing footer block (everything AFTER the '# ----' dash separator)."""
    size = path.stat().st_size
    with open(path, "rb") as fh:
        fh.seek(max(0, size - _FOOTER_BYTES))
        tail = fh.read().decode("utf-8", errors="replace")
    lines = tail.splitlines()
    # The footer starts after the last '# --...' (dash) separator line. If absent, no footer.
    start = None
    for i, line in enumerate(lines):
        if line.startswith("# --"):
            start = i
    if start is None:
        return {}
    footer = {}
    for line in lines[start + 1:]:
        m = _KV_RE.match(line)
        if m:
            footer[m.group(1)] = m.group(2).strip()
    return footer


def parse_file(path) -> "Run | None":
    """Quickly parses a log file (header+footer)."""
    path = Path(path)
    try:
        if not path.is_file():
            return None
        return Run(path, _read_header(path), _read_footer(path))
    except OSError:
        return None


def parse_full(path):
    """Also parses all body lines, for the detail view.

    Returns: (Run, [ (ts_str, level, message), ... ]).
    """
    run = parse_file(path)
    if run is None:
        return None, []
    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                m = _LINE_RE.match(raw.rstrip("\n"))
                if m:
                    lines.append((m.group(1), m.group(2), m.group(3)))
    except OSError:
        pass
    return run, lines


# ---------------------------------------------------------------------------
#  Scanning
# ---------------------------------------------------------------------------
def _job_log_dirs():
    """The unique logs/ directories of all registered jobs."""
    from scheduler.models import Job
    dirs = {}
    for job in Job.objects.all():
        try:
            d = Path(job.script_path).resolve().parent / settings.LOG_DIRNAME
        except (OSError, ValueError):
            continue
        dirs[str(d)] = d
    return list(dirs.values())


def list_runs_for_job(job) -> list:
    """Returns all .log files in a job's script directory (newest→oldest)."""
    log_dir = Path(job.script_path).resolve().parent / settings.LOG_DIRNAME
    return _scan_dir(log_dir)


def _scan_dir(log_dir: Path) -> list:
    runs = []
    if not log_dir.is_dir():
        return runs
    for entry in log_dir.glob("*.log"):
        run = parse_file(entry)
        if run is not None:
            runs.append(run)
    runs.sort(key=lambda r: r.started or _dt.datetime.min.replace(tzinfo=_dt.UTC),
              reverse=True)
    return runs


def list_all_runs() -> list:
    """Returns runs from all job log directories (newest→oldest)."""
    runs = []
    for d in _job_log_dirs():
        runs.extend(_scan_dir(d))
    runs.sort(key=lambda r: r.started or _dt.datetime.min.replace(tzinfo=_dt.UTC),
              reverse=True)
    return runs


def runs_since(cutoff) -> list:
    """Runs that started after the given (aware) time."""
    return [r for r in list_all_runs() if r.started and r.started >= cutoff]


def is_job_running(job) -> bool:
    """Does the job currently have a running execution?"""
    for run in list_runs_for_job(job):
        if run.is_running:
            return True
    return False


# ---------------------------------------------------------------------------
#  Token (safe file reference in URLs)
# ---------------------------------------------------------------------------
def encode_token(path) -> str:
    raw = str(Path(path).resolve()).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_token(token: str) -> "Path | None":
    """Converts a token to a file path and validates security (is it within an allowed log dir)."""
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    path = Path(raw).resolve()
    if path.suffix != ".log":
        return None
    allowed = _job_log_dirs()
    if any(_is_within(path, d) for d in allowed):
        return path
    return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def get_run(token: str):
    """Run (header+footer) from a token. None if invalid/unauthorized."""
    path = decode_token(token)
    return parse_file(path) if path else None


def get_run_full(token: str):
    path = decode_token(token)
    if not path:
        return None, []
    return parse_full(path)


# ---------------------------------------------------------------------------
#  Retention (old log cleanup)
# ---------------------------------------------------------------------------
def cleanup_old_logs(retention_days: int | None = None) -> int:
    """Deletes .log files older than N days. Returns the number of deleted files."""
    days = retention_days if retention_days is not None else settings.LOG_RETENTION_DAYS
    cutoff = timezone.now() - _dt.timedelta(days=days)
    cutoff_ts = cutoff.timestamp()
    removed = 0
    for d in _job_log_dirs():
        if not d.is_dir():
            continue
        for entry in d.glob("*.log"):
            try:
                if entry.stat().st_mtime < cutoff_ts:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
    return removed
