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
            "grace_period_seconds": 300,
            "is_active": True,
            "env_vars_text": "",
            "run_parameters_text": "",
        }
        data.update(overrides)
        return data

    def test_valid(self):
        self.assertTrue(JobForm(data=self._data()).is_valid())

    def test_env_and_params_parsed(self):
        form = JobForm(data=self._data(
            env_vars_text="API_URL=https://x\nDEBUG=1",
            run_parameters_text="TARGET\nMODE=fast",
        ))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["env_vars_text"], {"API_URL": "https://x", "DEBUG": "1"})
        params = form.cleaned_data["run_parameters_text"]
        self.assertEqual(params[0]["name"], "TARGET")
        self.assertEqual(params[1]["default"], "fast")

    def test_invalid_env_key_rejected(self):
        form = JobForm(data=self._data(env_vars_text="bad key=1"))
        self.assertFalse(form.is_valid())
        self.assertIn("env_vars_text", form.errors)

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
    def _data(self, **overrides):
        data = {
            "provider": "SLACK",
            "webhook_url": "https://hooks.slack.com/services/abc",
            "notify_on_failure": True,
            "notify_on_timeout": True,
            "email_enabled": False,
            "email_recipients": "",
            "min_consecutive_failures": 1,
            "notify_on_recovery": True,
            "notify_on_missed": True,
        }
        data.update(overrides)
        return data

    def test_valid(self):
        self.assertTrue(NotificationSettingForm(data=self._data()).is_valid())

    def test_empty_webhook_allowed(self):
        form = NotificationSettingForm(data=self._data(
            provider="TEAMS", webhook_url="", notify_on_failure=False, notify_on_timeout=False,
        ))
        self.assertTrue(form.is_valid())

    def test_email_channel(self):
        form = NotificationSettingForm(data=self._data(
            email_enabled=True, email_recipients="a@b.com, c@d.com", min_consecutive_failures=3,
        ))
        self.assertTrue(form.is_valid(), form.errors)
