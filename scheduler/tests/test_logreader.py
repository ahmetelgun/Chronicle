"""logreader service — file scanning/parsing tests."""
from __future__ import annotations

import datetime as _dt

from django.test import override_settings

from scheduler.models import Job
from scheduler.services import logreader
from scheduler.tests.base import ScriptTestCase, write_run_log


class LogReaderTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        # Place the script inside script_root; log directory = script_root/logs.
        self.job = Job.objects.create(name="J", script_path=self.ok_script)
        self.log_dir = str(self.job.script_log_dir)

    def test_parse_finished_run(self):
        write_run_log(self.log_dir, "J", status="SUCCESS",
                      events={"email": 18, "warning": 1}, metrics={"emails_sent": 18},
                      cpu_pct=55.0, rss=120.0)
        runs = logreader.list_runs_for_job(self.job)
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual(r.status, "SUCCESS")
        self.assertFalse(r.is_running)
        self.assertEqual(r.event_summary["email"], 18)
        self.assertEqual(r.metric_summary["emails_sent"], 18)
        self.assertEqual(r.cpu_pct, 55.0)
        self.assertEqual(r.max_rss_mb, 120.0)

    def test_running_when_no_footer_and_pid_alive(self):
        write_run_log(self.log_dir, "J", finished=False, pid=__import__("os").getpid())
        runs = logreader.list_runs_for_job(self.job)
        self.assertTrue(runs[0].is_running)
        self.assertTrue(logreader.is_job_running(self.job))

    def test_aborted_when_no_footer_and_pid_dead(self):
        write_run_log(self.log_dir, "J", finished=False, pid=999999)
        runs = logreader.list_runs_for_job(self.job)
        self.assertEqual(runs[0].status, "ABORTED")
        self.assertTrue(runs[0].is_failure)
        self.assertFalse(logreader.is_job_running(self.job))

    def test_failure_status(self):
        write_run_log(self.log_dir, "J", status="FAILED", exit_code=1)
        self.assertTrue(logreader.list_runs_for_job(self.job)[0].is_failure)

    def test_sorting_newest_first(self):
        old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=2)
        write_run_log(self.log_dir, "J", started=old, fname="old.log")
        write_run_log(self.log_dir, "J", fname="new.log")
        runs = logreader.list_runs_for_job(self.job)
        self.assertEqual(len(runs), 2)
        self.assertGreater(runs[0].started, runs[1].started)

    def test_parse_full_returns_body_lines(self):
        write_run_log(self.log_dir, "J", body=[
            "2026-06-11 09:00:00.001  OUT     hello",
            "2026-06-11 09:00:00.002  EVENT   [email] To: a@b.com",
            "2026-06-11 09:00:00.003  ERROR   crashed",
        ])
        run = logreader.list_runs_for_job(self.job)[0]
        _, lines = logreader.parse_full(run.path)
        levels = [lvl for _t, lvl, _m in lines]
        self.assertIn("EVENT", levels)
        self.assertIn("ERROR", levels)

    def test_runs_since_filters_by_time(self):
        from django.utils import timezone
        old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=48)
        write_run_log(self.log_dir, "J", started=old, fname="old.log")
        write_run_log(self.log_dir, "J", fname="new.log")
        recent = logreader.runs_since(timezone.now() - _dt.timedelta(hours=24))
        self.assertEqual(len(recent), 1)

    def test_token_roundtrip_and_security(self):
        path = write_run_log(self.log_dir, "J")
        token = logreader.encode_token(path)
        self.assertIsNotNone(logreader.decode_token(token))
        # A path outside the permitted log directory should be rejected.
        bad = logreader.encode_token("/etc/passwd.log")
        self.assertIsNone(logreader.decode_token(bad))
        # Malformed token.
        self.assertIsNone(logreader.decode_token("!!!notbase64!!!"))

    def test_get_run_via_token(self):
        path = write_run_log(self.log_dir, "J", status="SUCCESS")
        token = logreader.encode_token(path)
        run = logreader.get_run(token)
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "SUCCESS")

    def test_custom_header_and_footer_fields(self):
        import os
        d = self.log_dir
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "custom.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "# ===================== EXECUTION LOG (UTC) =====================\n"
                "# job:        J\n"
                "# started:    2026-06-11 09:00:00.000\n"
                "# env: production\n"
                "# version: 2.3.1\n"
                "# ==============================================================\n"
                "2026-06-11 09:00:00.001  OUT     hi\n"
                "# --------------------------------------------------------------\n"
                "# status:           SUCCESS\n"
                "# exit_code:        0\n"
                "# finished:         2026-06-11 09:00:01.000\n"
                "# summary_events:   -\n"
                "# summary_metrics:  -\n"
                "# recipients_total: 20\n"
                "# delivery_rate_pct: 85.0\n"
                "# ==============================================================\n"
            )
        run = logreader.parse_file(path)
        self.assertEqual(run.header_extra.get("env"), "production")
        self.assertEqual(run.header_extra.get("version"), "2.3.1")
        self.assertEqual(run.footer_extra.get("recipients_total"), "20")
        self.assertEqual(run.footer_extra.get("delivery_rate_pct"), "85.0")
        # Reserved fields should not leak into extra.
        self.assertNotIn("status", run.footer_extra)
        self.assertNotIn("job", run.header_extra)

    def test_cleanup_old_logs(self):
        import os
        import time
        old_path = write_run_log(self.log_dir, "J", fname="old.log")
        # Set mtime to 40 days ago.
        old = time.time() - 40 * 86400
        os.utime(old_path, (old, old))
        write_run_log(self.log_dir, "J", fname="fresh.log")
        removed = logreader.cleanup_old_logs(retention_days=30)
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old_path))
