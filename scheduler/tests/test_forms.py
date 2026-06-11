"""forms.py tests."""
from __future__ import annotations

from django.test import TestCase

from scheduler.forms import JobForm, NotificationSettingForm


class JobFormTests(TestCase):
    def _data(self, **overrides):
        data = {
            "name": "Backup",
            "description": "",
            "script_path": "/opt/scripts/backup.sh",
            "working_directory": "",
            "cron_expression": "0 2 * * *",
            "timeout_seconds": 3600,
            "is_active": True,
        }
        data.update(overrides)
        return data

    def test_valid(self):
        self.assertTrue(JobForm(data=self._data()).is_valid())

    def test_empty_cron_allowed(self):
        form = JobForm(data=self._data(cron_expression=""))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["cron_expression"], "")

    def test_invalid_cron_rejected(self):
        form = JobForm(data=self._data(cron_expression="99 99 * * *"))
        self.assertFalse(form.is_valid())
        self.assertIn("cron_expression", form.errors)

    def test_timeout_too_small(self):
        form = JobForm(data=self._data(timeout_seconds=0))
        self.assertFalse(form.is_valid())
        self.assertIn("timeout_seconds", form.errors)

    def test_timeout_too_large(self):
        form = JobForm(data=self._data(timeout_seconds=999999))
        self.assertFalse(form.is_valid())
        self.assertIn("timeout_seconds", form.errors)


class NotificationSettingFormTests(TestCase):
    def test_valid(self):
        form = NotificationSettingForm(data={
            "provider": "SLACK",
            "webhook_url": "https://hooks.slack.com/services/abc",
            "notify_on_failure": True,
            "notify_on_timeout": True,
        })
        self.assertTrue(form.is_valid())

    def test_empty_webhook_allowed(self):
        form = NotificationSettingForm(data={
            "provider": "TEAMS",
            "webhook_url": "",
            "notify_on_failure": False,
            "notify_on_timeout": False,
        })
        self.assertTrue(form.is_valid())
