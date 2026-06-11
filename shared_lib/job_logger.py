"""
job_logger.py — Script-side logging library (format compatible with Job Scheduler).

The script writes its own execution log. This way, whether triggered by the
scheduler or run independently via cron/manually, it produces the same standard
`.log` file that is visible to the dashboard.

File location/name:
    <script_dir>/logs/<script_stem>-<YYYYmmddHHMMSS_UTC>-<pid>.log
    (The PID suffix prevents collisions between runs in the same second.)
Each file = one run. The presence of a footer = the job has finished.

Usage (Python):

    import job_logger
    with job_logger.run(header={"env": "production", "version": "1.2.3"}) as log:
        print("normal output")           # logged as OUT via tee
        log.info("started")
        log.event("email", f"To: {addr} | subject: {subj}")
        log.metric("emails_sent", 42)
        log.footer("records_processed", 1234)   # custom field in footer
    # on exit the footer (status + resources + summary + custom) is written

Custom fields:
  * Header:  run(header={"key": "value", ...})  -> written to the header block.
  * Footer:  log.footer("key", value)           -> written to the footer block.
  Keys are normalized to [a-z0-9_]; values are collapsed to a single line.

All timestamps are in UTC.
"""
from __future__ import annotations

import datetime as _dt
import os
import signal
import sys
import threading

try:
    import psutil  # optional: if missing, resource metrics are left empty
except ImportError:  # pragma: no cover
    psutil = None

_LEVEL_W = 7
_SEVERITY = {"info": "INFO", "warning": "WARN", "error": "ERROR"}


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _ts(dt: _dt.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


class _ResourceSampler:
    """Samples our own process (and child processes) to measure peak RAM + CPU time."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self._max_rss = 0
        self._cpu = 0.0

    def start(self):
        if psutil is None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            me = psutil.Process(os.getpid())
        except psutil.Error:
            return
        while not self._stop.is_set():
            self._sample(me)
            self._stop.wait(0.1)
        self._sample(me)

    def _sample(self, me):
        try:
            procs = [me] + me.children(recursive=True)
        except psutil.Error:
            return
        rss = cpu = 0.0
        for p in procs:
            try:
                rss += p.memory_info().rss
                t = p.cpu_times()
                cpu += t.user + t.system
            except psutil.Error:
                continue
        self._max_rss = max(self._max_rss, rss)
        self._cpu = max(self._cpu, cpu)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def stats(self, duration):
        rss_mb = round(self._max_rss / (1024 * 1024), 1) if self._max_rss else None
        cpu = round(self._cpu, 2) if self._cpu else 0.0
        pct = round((cpu / duration) * 100, 1) if duration and duration > 0 else None
        return cpu, pct, rss_mb


class _Tee:
    """Routes written output to both the original stream and the log (OUT/ERR)."""

    def __init__(self, original, logger, level):
        self._orig = original
        self._logger = logger
        self._level = level
        self._buf = ""

    def write(self, s):
        self._orig.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._logger._raw_line(self._level, line)

    def flush(self):
        self._orig.flush()

    def isatty(self):
        return getattr(self._orig, "isatty", lambda: False)()


def _norm_key(key) -> str:
    """Reduces a custom field key to the [a-z0-9_] form."""
    import re
    k = re.sub(r"[^a-z0-9_]+", "_", str(key).strip().lower()).strip("_")
    return k or "field"


def _norm_val(value) -> str:
    return " ".join(str(value).splitlines()).strip()


class JobLogger:
    def __init__(self, job_name=None, *, tee=True, header=None):
        script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "script"
        self.script_path = script
        stem = os.path.splitext(os.path.basename(script))[0] or "script"
        self.started = _utc_now()
        log_dir = os.path.join(os.path.dirname(script), "logs")
        os.makedirs(log_dir, exist_ok=True)
        # PID suffix to avoid collisions between runs in the same second.
        fname = f"{stem}-{self.started.strftime('%Y%m%d%H%M%S')}-{os.getpid()}.log"
        self.path = os.path.join(log_dir, fname)

        self.job_name = job_name or os.environ.get("JOB_NAME") or stem
        self.trigger = os.environ.get("JOB_TRIGGER", "INDEPENDENT")
        self.user = os.environ.get("JOB_USER") or _os_user()

        self._lock = threading.Lock()
        self._fh = open(self.path, "w", encoding="utf-8", buffering=1)
        self.event_summary: dict[str, int] = {}
        self.metric_summary: dict[str, float] = {}
        self._error_parts: list[str] = []
        self._footer_extra: dict[str, str] = {}
        self._closed = False

        self._sampler = _ResourceSampler()
        self._tee = tee
        self._saved_stdout = self._saved_stderr = None

        self._write_header(header or {})
        self._sampler.start()
        if tee:
            self._saved_stdout, self._saved_stderr = sys.stdout, sys.stderr
            sys.stdout = _Tee(self._saved_stdout, self, "OUT")
            sys.stderr = _Tee(self._saved_stderr, self, "ERR")

        # On SIGTERM (scheduler timeout-kill), write the footer and exit.
        try:
            signal.signal(signal.SIGTERM, self._on_sigterm)
        except (ValueError, OSError):  # skip if not on the main thread
            pass

    # ---- internal writing ----
    def _w(self, text):
        if not self._closed:
            self._fh.write(text + "\n")

    def _write_header(self, extra: dict):
        self._w("# ===================== EXECUTION LOG (UTC) =====================")
        self._w(f"# job:        {self.job_name}")
        self._w(f"# script:     {self.script_path}")
        self._w(f"# cwd:        {os.getcwd()}")
        self._w(f"# trigger:    {self.trigger}")
        self._w(f"# user:       {self.user}")
        self._w(f"# pid:        {os.getpid()}")
        self._w(f"# started:    {_ts(self.started)}")
        # Custom header fields (so they don't collide with built-ins).
        for k, v in extra.items():
            key = _norm_key(k)
            if key not in _RESERVED:
                self._w(f"# {key}: {_norm_val(v)}")
        self._w("# ==============================================================")

    def _raw_line(self, level, payload):
        with self._lock:
            self._w(f"{_ts(_utc_now())}  {level:<{_LEVEL_W}} {payload}")
            if level in ("ERROR", "ERR") and len(self._error_parts) < 8 and payload.strip():
                self._error_parts.append(payload.strip())

    # ---- public API ----
    def out(self, message):
        self._raw_line("OUT", str(message))

    def info(self, message):
        self._raw_line("INFO", str(message))

    def warn(self, message):
        self.event("warning", message)

    def error(self, message):
        self.event("error", message)

    def event(self, category, message=""):
        cat = str(category).strip().replace(" ", "_").lower()[:50] or "info"
        msg = " ".join(str(message).splitlines())
        level = _SEVERITY.get(cat, "EVENT")
        payload = msg if cat in _SEVERITY else f"[{cat}] {msg}".rstrip()
        self._raw_line(level, payload)
        with self._lock:
            self.event_summary[cat] = self.event_summary.get(cat, 0) + 1

    def metric(self, name, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        n = str(name).replace(" ", "_")[:100]
        self._raw_line("METRIC", f"{n}={v:g}")
        with self._lock:
            self.metric_summary[n] = self.metric_summary.get(n, 0) + v

    def footer(self, key, value):
        """Adds a custom field to the footer (cannot collide with built-in fields)."""
        k = _norm_key(key)
        if k not in _RESERVED:
            with self._lock:
                self._footer_extra[k] = _norm_val(value)

    # ---- shutdown ----
    def _on_sigterm(self, signum, frame):
        self.close(status="TIMEOUT")
        os._exit(143)

    def close(self, status="SUCCESS"):
        if self._closed:
            return
        # restore the tee.
        if self._tee and self._saved_stdout is not None:
            sys.stdout, sys.stderr = self._saved_stdout, self._saved_stderr
        self._sampler.stop()
        finished = _utc_now()
        duration = round((finished - self.started).total_seconds(), 2)
        cpu, pct, rss = self._sampler.stats(duration)
        with self._lock:
            self._w("# --------------------------------------------------------------")
            self._w(f"# status:           {status}")
            self._w(f"# exit_code:        {0 if status == 'SUCCESS' else 1}")
            self._w(f"# finished:         {_ts(finished)}")
            self._w(f"# duration_sec:     {duration:g}")
            self._w(f"# cpu_time_sec:     {cpu:g}")
            self._w(f"# cpu_pct:          {pct if pct is not None else '-'}")
            self._w(f"# max_rss_mb:       {rss if rss is not None else '-'}")
            self._w(f"# summary_events:   {_kv(self.event_summary)}")
            self._w(f"# summary_metrics:  {_kv(self.metric_summary)}")
            for k, v in self._footer_extra.items():
                self._w(f"# {k}: {v}")
            self._w("# ==============================================================")
            self._fh.close()
            self._closed = True

    # ---- context manager ----
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close(status="SUCCESS" if exc_type is None else "FAILED")
        return False  # do not swallow the exception


# Built-in (reserved) field names — custom header/footer cannot override these.
_RESERVED = {
    "job", "script", "cwd", "trigger", "user", "pid", "started",
    "status", "exit_code", "finished", "duration_sec", "cpu_time_sec",
    "cpu_pct", "max_rss_mb", "summary_events", "summary_metrics",
}


def run(job_name=None, *, tee=True, header=None) -> JobLogger:
    """Returns a JobLogger to be used as a context manager."""
    return JobLogger(job_name, tee=tee, header=header)


def _kv(d):
    return " ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                    for k, v in d.items()) or "-"


def _os_user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:  # pragma: no cover
        return "-"
