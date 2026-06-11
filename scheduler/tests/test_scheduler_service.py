"""scheduler.py — APScheduler cron engine tests."""
from __future__ import annotations

from unittest import mock

from apscheduler.triggers.cron import CronTrigger
from django.test import TestCase

from scheduler.models import Job
from scheduler.services import scheduler as sched


class ParseCronTests(TestCase):
    def test_parse_valid(self):
        trigger = sched._parse_cron("0 2 * * *")
        self.assertIsInstance(trigger, CronTrigger)

    def test_parse_invalid_raises(self):
        with self.assertRaises(ValueError):
            sched._parse_cron("not-a-cron")


class ExecuteScheduledJobTests(TestCase):
    def test_runs_active_job(self):
        job = Job.objects.create(name="J", script_path="/x", is_active=True)
        with mock.patch(
            "scheduler.services.executor.run_job_sync"
        ) as run:
            sched._execute_scheduled_job(job.pk)
        run.assert_called_once()
        # Should be called with the SCHEDULER trigger type
        self.assertEqual(run.call_args.kwargs["trigger_type"], "SCHEDULER")

    def test_skips_inactive_job(self):
        job = Job.objects.create(name="J", script_path="/x", is_active=False)
        with mock.patch("scheduler.services.executor.run_job_sync") as run:
            sched._execute_scheduled_job(job.pk)
        run.assert_not_called()

    def test_missing_job_is_safe(self):
        with mock.patch("scheduler.services.executor.run_job_sync") as run:
            sched._execute_scheduled_job(999999)
        run.assert_not_called()

    def test_already_running_is_handled(self):
        job = Job.objects.create(name="J", script_path="/x")
        from scheduler.services import executor
        with mock.patch(
            "scheduler.services.executor.run_job_sync",
            side_effect=executor.JobAlreadyRunningError("running"),
        ):
            # Exception should not leak
            sched._execute_scheduled_job(job.pk)

    def test_execution_error_is_handled(self):
        job = Job.objects.create(name="J", script_path="/x")
        from scheduler.services import executor
        with mock.patch(
            "scheduler.services.executor.run_job_sync",
            side_effect=executor.ExecutionError("error"),
        ):
            sched._execute_scheduled_job(job.pk)


class StartSyncShutdownTests(TestCase):
    def tearDown(self):
        sched.shutdown()
        super().tearDown()

    def test_start_sync_and_shutdown(self):
        sched.start()
        # Idempotent: a second start should not cause issues
        sched.start()

        Job.objects.create(
            name="Scheduled", script_path="/x",
            cron_expression="0 3 * * *", is_active=True,
        )
        bad = Job.objects.create(
            name="BadCron", script_path="/x",
            cron_expression="totally invalid", is_active=True,
        )
        sched.sync_jobs()

        job_ids = {j.id for j in sched._scheduler.get_jobs()}
        self.assertIn("internal_sync_jobs", job_ids)
        # The job with a valid cron should have been added
        self.assertTrue(any(i.startswith("scriptjob_") for i in job_ids))
        # The job with an invalid cron should be skipped (not added)
        self.assertNotIn(f"scriptjob_{bad.pk}", job_ids)

    def test_sync_removes_stale_jobs(self):
        sched.start()
        job = Job.objects.create(
            name="Temp", script_path="/x", cron_expression="0 4 * * *", is_active=True
        )
        sched.sync_jobs()
        self.assertIsNotNone(sched._scheduler.get_job(f"scriptjob_{job.pk}"))

        # Deactivate -> should be removed after sync
        job.is_active = False
        job.save()
        sched.sync_jobs()
        self.assertIsNone(sched._scheduler.get_job(f"scriptjob_{job.pk}"))

    def test_sync_without_scheduler_is_noop(self):
        sched.shutdown()
        # The call should not raise when _scheduler is None
        sched.sync_jobs()
