"""models.py tests (file-based execution)."""
from __future__ import annotations

import os

from django.test import TestCase
from django.utils import timezone

from scheduler.models import Job, NotificationSetting
from scheduler.tests.base import ScriptTestCase, make_user, write_run_log


class JobModelTests(TestCase):
    def test_str_and_url(self):
        job = Job.objects.create(name="Backup", script_path="/opt/scripts/b.sh")
        self.assertEqual(str(job), "Backup")
        self.assertIn(str(job.pk), job.get_absolute_url())

    def test_is_scheduled(self):
        job = Job.objects.create(name="J", script_path="/x", cron_expression="0 2 * * *")
        self.assertTrue(job.is_scheduled)
        job.is_active = False
        self.assertFalse(job.is_scheduled)

    def test_next_run_time(self):
        job = Job.objects.create(name="J", script_path="/x", cron_expression="0 2 * * *")
        self.assertIsNotNone(job.next_run_time())
        job.cron_expression = ""
        self.assertIsNone(job.next_run_time())

    def test_duplicate(self):
        user = make_user("creator")
        src = Job.objects.create(
            name="Backup", script_path="/opt/scripts/b.sh",
            cron_expression="0 2 * * *", timeout_seconds=120, is_active=True,
        )
        clone = src.duplicate(created_by=user)
        self.assertEqual(clone.name, "Backup (copy)")
        self.assertFalse(clone.is_active)
        self.assertEqual(clone.created_by, user)

    def test_duplicate_name_increment(self):
        src = Job.objects.create(name="Job", script_path="/x")
        self.assertEqual(src.duplicate().name, "Job (copy)")
        self.assertEqual(src.duplicate().name, "Job (copy 2)")

    def test_unique_copy_name_maxlen(self):
        long = "X" * 150
        Job.objects.create(name=long, script_path="/x")
        self.assertLessEqual(len(Job.unique_copy_name(long)), 150)


class JobFileBasedStatusTests(ScriptTestCase):
    def test_last_execution_and_is_running_from_files(self):
        job = Job.objects.create(name="J", script_path=self.ok_script)
        self.assertIsNone(job.last_execution)
        self.assertFalse(job.is_running)

        write_run_log(str(job.script_log_dir), "J", status="SUCCESS")
        self.assertIsNotNone(job.last_execution)
        self.assertEqual(job.last_execution.status, "SUCCESS")
        self.assertFalse(job.is_running)

        # No footer + live pid -> running.
        write_run_log(str(job.script_log_dir), "J", finished=False,
                      pid=os.getpid(), fname="running.log")
        self.assertTrue(job.is_running)

    def test_script_log_dir(self):
        job = Job.objects.create(name="J", script_path=self.ok_script)
        self.assertTrue(str(job.script_log_dir).endswith("logs"))


class NotificationSettingTests(TestCase):
    def test_singleton(self):
        s = NotificationSetting.load()
        s.webhook_url = "https://hooks.slack.com/x"
        s.save()
        self.assertEqual(NotificationSetting.load().webhook_url, "https://hooks.slack.com/x")
        self.assertEqual(NotificationSetting.objects.count(), 1)
