"""notifications.py — Run-based webhook notification tests."""
from __future__ import annotations

from unittest import mock

import requests

from scheduler.models import Job, NotificationSetting
from scheduler.services import logreader, notifications
from scheduler.tests.base import ScriptTestCase, write_run_log


class NotificationTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(name="Backup", script_path=self.ok_script)
        self.log_dir = str(self.job.script_log_dir)

    def _failed_run(self, status="FAILED"):
        path = write_run_log(
            self.log_dir, "Backup", status=status, exit_code=1,
            body=["2026-06-11 09:00:00.001  ERROR   critical error occurred"],
        )
        return logreader.parse_file(path)

    def _set(self, url="https://hooks.slack.com/x", **kw):
        s = NotificationSetting.load()
        s.webhook_url = url
        for k, v in kw.items():
            setattr(s, k, v)
        s.save()

    def test_skipped_without_webhook(self):
        self._set(url="")
        self.assertFalse(notifications.send_failure_notification(self._failed_run()))

    def test_slack_payload(self):
        self._set(provider=NotificationSetting.Provider.SLACK)
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(notifications.send_failure_notification(self._failed_run()))
        self.assertIn("blocks", post.call_args.kwargs["json"])

    def test_teams_payload(self):
        self._set(provider=NotificationSetting.Provider.TEAMS)
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(notifications.send_failure_notification(self._failed_run()))
        self.assertEqual(post.call_args.kwargs["json"]["@type"], "MessageCard")

    def test_failure_flag_off(self):
        self._set(notify_on_failure=False)
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            self.assertFalse(notifications.send_failure_notification(self._failed_run()))
        post.assert_not_called()

    def test_timeout_flag_off(self):
        self._set(notify_on_timeout=False)
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            self.assertFalse(
                notifications.send_failure_notification(self._failed_run(status="TIMEOUT"))
            )
        post.assert_not_called()

    def test_request_exception(self):
        self._set()
        with mock.patch("scheduler.services.notifications.requests.post",
                        side_effect=requests.RequestException("down")):
            self.assertFalse(notifications.send_failure_notification(self._failed_run()))

    def test_error_preview_from_file(self):
        self._set()
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            notifications.send_failure_notification(self._failed_run())
        self.assertIn("critical error", str(post.call_args.kwargs["json"]))
