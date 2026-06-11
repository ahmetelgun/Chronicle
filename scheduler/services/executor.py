"""
Execution Engine — runs scripts safely via subprocess.

FILE-BASED MODEL:
  * The SCRIPT ITSELF writes the log file (via shared_lib/job_logger). The
    executor does not write logs and keeps no execution record in the DB.
  * Concurrency control is done via flock (.lock file).
  * The executor only: validates, locks, runs, applies a timeout, and — if the
    run fails — reads the produced log file and sends a notification.
"""
from __future__ import annotations

import fcntl
import logging
import os
import re
import signal
import subprocess
import threading
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("scheduler")


class ExecutionError(Exception):
    """Validation/lock errors that occur before the script is run."""


class JobAlreadyRunningError(ExecutionError):
    """The same script is already running (concurrency lock)."""


# ----------------------------------------------------------------------------
#  Security validation
# ----------------------------------------------------------------------------
def validate_script_path(script_path: str) -> Path:
    """Validates the script path against security rules (under the allowed root)."""
    allowed_root = Path(settings.SCRIPT_ALLOWED_ROOT).resolve()
    try:
        resolved = Path(script_path).resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise ExecutionError(f"Script not found: {script_path}") from exc
    if not resolved.is_relative_to(allowed_root):
        raise ExecutionError(
            f"Security: script is outside the allowed directory ({allowed_root}): {resolved}"
        )
    if not resolved.is_file():
        raise ExecutionError(f"Script is not a file: {resolved}")
    return resolved


def _resolve_cwd(job, script_file: Path) -> Path:
    if job.working_directory.strip():
        cwd = Path(job.working_directory).resolve()
        if not cwd.is_dir():
            raise ExecutionError(f"Invalid working directory: {cwd}")
        return cwd
    return script_file.parent


def build_pythonpath(script_dir: Path) -> str:
    """PYTHONPATH passed to the subprocess (shared modules + script directory)."""
    raw = getattr(settings, "SCRIPT_PYTHONPATH", "") or ""
    parts: list[str] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            resolved = str(Path(chunk).resolve())
            if resolved not in parts:
                parts.append(resolved)
    script_dir_str = str(script_dir.resolve())
    if script_dir_str not in parts:
        parts.append(script_dir_str)
    return os.pathsep.join(parts)


# ----------------------------------------------------------------------------
#  Concurrency lock (flock)
# ----------------------------------------------------------------------------
def _acquire_lock(job):
    """
    Locks a .lock file in the script's logs/ directory via flock.
    Raises JobAlreadyRunningError if the lock cannot be acquired.
    Returns: (lock_fd, script_file, cwd) — fd must be kept open for the run.
    """
    script_file = validate_script_path(job.script_path)
    cwd = _resolve_cwd(job, script_file)
    log_dir = script_file.parent / settings.LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_path = log_dir / f".{script_file.stem}.lock"

    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        raise JobAlreadyRunningError(f"'{job.name}' is already running; trigger blocked.")
    return fd, script_file, cwd


def _release_lock(fd) -> None:
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        fd.close()
    except OSError:  # pragma: no cover
        pass


# ----------------------------------------------------------------------------
#  Execution core
# ----------------------------------------------------------------------------
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _merge_env(env: dict, extra) -> None:
    """Merges extra env vars into env, keeping only valid string key/values."""
    if not extra:
        return
    for key, value in dict(extra).items():
        key = str(key)
        if _ENV_KEY_RE.match(key):
            env[key] = str(value)


def _run_subprocess(job, *, trigger_type: str, user, script_file: Path, cwd: Path,
                    extra_env=None) -> None:
    """Runs the script, applies a timeout, and sends a notification on failure."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(cwd),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "JOB_NAME": job.name,
        "JOB_TRIGGER": trigger_type,
        "JOB_USER": user.get_username() if (user and getattr(user, "is_authenticated", False)) else "-",
    }
    pythonpath = build_pythonpath(script_file.parent)
    if pythonpath:
        env["PYTHONPATH"] = pythonpath

    # Static per-job env vars, then run-time parameters (validated, string values).
    _merge_env(env, getattr(job, "env_vars", None))
    _merge_env(env, extra_env)

    logger.info("Starting script: %s -> %s (cwd=%s)", job.name, script_file, cwd)

    try:
        proc = subprocess.Popen(
            [str(script_file)],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.DEVNULL,  # the script writes its own log file
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        logger.error("Could not start process (%s): %s", job.name, exc)
        return

    try:
        exit_code = proc.wait(timeout=job.timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.warning("Timeout (%s s) — killing process: %s",
                       job.timeout_seconds, job.name)
        _kill_process_group(proc)
        exit_code = proc.wait()

    logger.info("Script finished: %s (exit=%s)", job.name, exit_code)
    _evaluate_notifications(job)


def _kill_process_group(proc) -> None:
    """On timeout, kills the process group with SIGTERM (job_logger writes footer) then SIGKILL."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except (ProcessLookupError, PermissionError):
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _evaluate_notifications(job) -> None:
    """
    Smart routing based on the run history in the log files:
      * failure  — alert once the consecutive-failure count reaches the threshold
      * recovery — alert when this run succeeded but the previous one had failed
    Notifications must never break the main flow.
    """
    try:
        from scheduler.models import NotificationSetting
        from scheduler.services import logreader, notifications

        runs = logreader.list_runs_for_job(job)
        if not runs:
            return
        current = runs[0]
        setting = NotificationSetting.load()

        if current.is_failure:
            consecutive = 0
            for r in runs:
                if r.is_failure:
                    consecutive += 1
                else:
                    break
            if consecutive >= setting.min_consecutive_failures:
                notifications.send_failure_notification(current)
        else:
            # Recovery: previous run was a failure.
            if len(runs) >= 2 and runs[1].is_failure:
                notifications.send_recovery_notification(current)
    except Exception:  # pragma: no cover - notifications must not break the main flow
        logger.exception("Unexpected error sending notification")


# ----------------------------------------------------------------------------
#  Public API
# ----------------------------------------------------------------------------
def run_job_async(job, *, trigger_type: str, user=None, extra_env=None) -> None:
    """
    Runs the script in the background (separate thread) — does not block the web request.
    The lock is acquired synchronously; if it cannot be acquired, JobAlreadyRunningError
    is raised immediately. `extra_env` carries run-time parameters as env vars.
    """
    lock_fd, script_file, cwd = _acquire_lock(job)

    def _worker():
        try:
            _run_subprocess(
                job, trigger_type=trigger_type, user=user,
                script_file=script_file, cwd=cwd, extra_env=extra_env,
            )
        finally:
            _release_lock(lock_fd)

    thread = threading.Thread(target=_worker, name=f"job-{job.pk}-exec", daemon=True)
    thread.start()


def run_job_sync(job, *, trigger_type: str, user=None, extra_env=None) -> None:
    """Synchronous execution (called from the scheduler thread pool)."""
    lock_fd, script_file, cwd = _acquire_lock(job)
    try:
        _run_subprocess(
            job, trigger_type=trigger_type, user=user,
            script_file=script_file, cwd=cwd, extra_env=extra_env,
        )
    finally:
        _release_lock(lock_fd)
