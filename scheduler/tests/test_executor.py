"""executor.py — file-based execution engine tests."""
from __future__ import annotations

import os
import time

from scheduler.models import Job
from scheduler.services import executor, logreader
from scheduler.tests.base import ScriptTestCase, make_script


class ValidateScriptPathTests(ScriptTestCase):
    def test_valid(self):
        self.assertTrue(str(executor.validate_script_path(self.ok_script)).endswith("ok.sh"))

    def test_not_found(self):
        with self.assertRaises(executor.ExecutionError):
            executor.validate_script_path(os.path.join(self.script_root, "yok.sh"))

    def test_outside_root(self):
        with self.assertRaises(executor.ExecutionError):
            executor.validate_script_path("/etc/hosts")

    def test_directory(self):
        with self.assertRaises(executor.ExecutionError):
            executor.validate_script_path(self.script_root)


class BuildPythonPathTests(ScriptTestCase):
    def test_includes_script_dir(self):
        from pathlib import Path
        pp = executor.build_pythonpath(Path(self.script_root))
        self.assertIn(self.script_root, pp)

    def test_includes_configured(self):
        from pathlib import Path
        with self.settings(SCRIPT_PYTHONPATH=self.script_root):
            pp = executor.build_pythonpath(Path(self.script_root))
        self.assertIn(self.script_root, pp)


class RunJobTests(ScriptTestCase):
    def test_runs_script_side_effect(self):
        # Have the script create a marker file; this verifies that it ran.
        marker = os.path.join(self.script_root, "ran.marker")
        script = make_script(
            self.script_root, "touch.sh", f"#!/bin/bash\ntouch '{marker}'\nexit 0\n"
        )
        job = Job.objects.create(name="T", script_path=script)
        executor.run_job_sync(job, trigger_type="MANUAL")
        self.assertTrue(os.path.exists(marker))

    def test_concurrency_lock(self):
        job = Job.objects.create(name="L", script_path=self.ok_script)
        # Acquire the lock manually; the second trigger should be blocked.
        fd, _sf, _cwd = executor._acquire_lock(job)
        try:
            with self.assertRaises(executor.JobAlreadyRunningError):
                executor.run_job_sync(job, trigger_type="MANUAL")
        finally:
            executor._release_lock(fd)
        # After the lock is released, it should be able to run again.
        executor.run_job_sync(job, trigger_type="MANUAL")

    def test_invalid_script_raises(self):
        job = Job.objects.create(name="E", script_path="/etc/hosts")
        with self.assertRaises(executor.ExecutionError):
            executor.run_job_sync(job, trigger_type="MANUAL")

    def test_timeout_kills_script(self):
        # Script sleeps 30s, timeout 1s -> should be killed (run takes ~1s).
        job = Job.objects.create(name="S", script_path=self.slow_script, timeout_seconds=1)
        start = time.time()
        executor.run_job_sync(job, trigger_type="MANUAL")
        self.assertLess(time.time() - start, 10)

    def test_run_async_lock_raises_immediately(self):
        job = Job.objects.create(name="A", script_path=self.ok_script)
        fd, _sf, _cwd = executor._acquire_lock(job)
        try:
            with self.assertRaises(executor.JobAlreadyRunningError):
                executor.run_job_async(job, trigger_type="MANUAL")
        finally:
            executor._release_lock(fd)

    def test_popen_oserror_is_handled(self):
        job = Job.objects.create(name="O", script_path=self.ok_script)
        from unittest import mock
        with mock.patch("scheduler.services.executor.subprocess.Popen",
                        side_effect=OSError("permission denied")):
            # Should return without crashing (error is swallowed, no log produced).
            executor.run_job_sync(job, trigger_type="MANUAL")

    def test_run_async_executes_in_thread(self):
        marker = os.path.join(self.script_root, "async.marker")
        script = make_script(
            self.script_root, "amark.sh", f"#!/bin/bash\ntouch '{marker}'\n"
        )
        job = Job.objects.create(name="AT", script_path=script)
        executor.run_job_async(job, trigger_type="MANUAL")
        # Wait for the background thread to finish.
        for _ in range(50):
            if os.path.exists(marker):
                break
            time.sleep(0.1)
        self.assertTrue(os.path.exists(marker))

    def test_notify_on_failure_reads_file(self):
        # Have the script write its own FAILED log file; executor reads it and notifies.
        script = make_script(
            self.script_root, "writelog.sh",
            "#!/bin/bash\n"
            "d=\"$(dirname \"$0\")/logs\"; mkdir -p \"$d\"\n"
            "f=\"$d/writelog-$(date -u +%Y%m%d%H%M%S).log\"\n"
            "{ echo '# started:    2026-06-11 09:00:00.000';"
            "  echo '2026-06-11 09:00:00.001  ERROR   boom';"
            "  echo '# status:           FAILED';"
            "  echo '# exit_code:        1'; } > \"$f\"\n"
            "exit 1\n",
        )
        job = Job.objects.create(name="WL", script_path=script)
        from unittest import mock
        with mock.patch("scheduler.services.notifications.send_failure_notification") as notify:
            executor.run_job_sync(job, trigger_type="MANUAL")
        notify.assert_called_once()
