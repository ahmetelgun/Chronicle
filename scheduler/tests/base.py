"""Shared test helpers: temporary script directory and user/role setup."""
from __future__ import annotations

import os
import stat
import tempfile

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings


def make_script(directory: str, name: str, body: str) -> str:
    """Creates an executable shell script in the given directory and returns its path."""
    path = os.path.join(directory, name)
    with open(path, "w") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class ScriptTestCase(TestCase):
    """
    Provides a temporary, permitted script root directory and points SCRIPT_ALLOWED_ROOT there.
    Ready-made scripts: ok.sh (exit 0), fail.sh (exit 3), slow.sh (sleep 30).
    """

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp(prefix="sched_test_")
        # Use the real path because SCRIPT_ALLOWED_ROOT is compared via resolve().
        self.script_root = os.path.realpath(self._tmpdir)

        self.ok_script = make_script(
            self.script_root, "ok.sh", "#!/bin/bash\necho 'ok-out'\nexit 0\n"
        )
        self.fail_script = make_script(
            self.script_root, "fail.sh",
            "#!/bin/bash\necho 'partial'\necho 'boom' >&2\nexit 3\n",
        )
        self.slow_script = make_script(
            self.script_root, "slow.sh", "#!/bin/bash\necho 'started'\nsleep 30\n"
        )

        self._settings_override = override_settings(SCRIPT_ALLOWED_ROOT=self.script_root)
        self._settings_override.enable()

    def tearDown(self):
        self._settings_override.disable()
        super().tearDown()


def write_run_log(log_dir, job_name, script="/x/s.py", *, status="SUCCESS",
                  trigger="MANUAL", user="tester", pid=None, started=None,
                  duration=1.5, cpu_pct=12.0, rss=64.0, exit_code=0,
                  events=None, metrics=None, body=None, finished=True,
                  fname=None, header_extra=None, footer_extra=None) -> str:
    """
    Produces a .log file in a format that logreader can parse.
    If finished=False, no footer is written (running/aborted scenario).
    """
    import datetime as _dt
    import os

    os.makedirs(log_dir, exist_ok=True)
    now = _dt.datetime.now(_dt.UTC) if started is None else started
    ts = now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    if pid is None:
        pid = os.getpid()
    fname = fname or f"{job_name}-{now.strftime('%Y%m%d%H%M%S')}-{id(object()) % 100000}.log"
    path = os.path.join(log_dir, fname)

    def kv(d):
        return " ".join(f"{k}={v}" for k, v in (d or {}).items()) or "-"

    lines = [
        "# ===================== EXECUTION LOG (UTC) =====================",
        f"# job:        {job_name}",
        f"# script:     {script}",
        f"# cwd:        /x",
        f"# trigger:    {trigger}",
        f"# user:       {user}",
        f"# pid:        {pid}",
        f"# started:    {ts}",
    ]
    for k, v in (header_extra or {}).items():
        lines.append(f"# {k}: {v}")
    lines.append("# ==============================================================")
    for ln in (body or []):
        lines.append(ln)
    if finished:
        lines += [
            "# --------------------------------------------------------------",
            f"# status:           {status}",
            f"# exit_code:        {exit_code}",
            f"# finished:         {ts}",
            f"# duration_sec:     {duration}",
            f"# cpu_time_sec:     1.0",
            f"# cpu_pct:          {cpu_pct}",
            f"# max_rss_mb:       {rss}",
            f"# summary_events:   {kv(events)}",
            f"# summary_metrics:  {kv(metrics)}",
        ]
        for k, v in (footer_extra or {}).items():
            lines.append(f"# {k}: {v}")
        lines.append("# ==============================================================")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def make_user(username: str, *, role: str | None = None,
              superuser: bool = False) -> User:
    """Creates a test user assigned to the given role (Django Group)."""
    if superuser:
        user = User.objects.create_superuser(username, f"{username}@x.com", "pass12345")
    else:
        user = User.objects.create_user(username, f"{username}@x.com", "pass12345")
    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


ADMIN = settings.ROLE_ADMIN
OPERATOR = settings.ROLE_OPERATOR
VIEWER = settings.ROLE_VIEWER
