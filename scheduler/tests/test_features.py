"""Tests for the new features: per-job env/params, missed-run, smart routing, trends."""
from __future__ import annotations

import datetime as _dt
from unittest import mock

from django.urls import reverse

from scheduler.models import Job, NotificationSetting
from scheduler.services import executor, notifications
from scheduler.services import scheduler as sched
from scheduler.tests.base import ADMIN, OPERATOR, VIEWER, ScriptTestCase, make_user, write_run_log


def _ago(**kw):
    return _dt.datetime.now(_dt.UTC) - _dt.timedelta(**kw)


# ---------------------------------------------------------------------------
#  Per-job env + parameterized run
# ---------------------------------------------------------------------------
class EnvAndParamsTests(ScriptTestCase):
    def test_merge_env_filters_invalid_keys(self):
        env = {}
        executor._merge_env(env, {"GOOD": "1", "bad key": "x", "A1": 2})
        self.assertEqual(env["GOOD"], "1")
        self.assertEqual(env["A1"], "2")          # coerced to str
        self.assertNotIn("bad key", env)

    def test_run_now_passes_parameters_as_env(self):
        job = Job.objects.create(
            name="P", script_path=self.ok_script, is_active=True,
            run_parameters=[{"name": "TARGET", "default": "x", "label": "TARGET"}],
        )
        self.client.force_login(make_user("admin", role=ADMIN))
        with mock.patch("scheduler.services.executor.run_job_async") as run:
            self.client.post(reverse("job_run", args=[job.pk]), {"TARGET": "prod"})
        self.assertEqual(run.call_args.kwargs["extra_env"], {"TARGET": "prod"})

    def test_run_form_renders_for_operator(self):
        job = Job.objects.create(name="P", script_path=self.ok_script,
                                 run_parameters=[{"name": "X", "default": "", "label": "X"}])
        self.client.force_login(make_user("op", role=OPERATOR))
        resp = self.client.get(reverse("job_run_form", args=[job.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "X")


# ---------------------------------------------------------------------------
#  Smart routing (consecutive failures + recovery)
# ---------------------------------------------------------------------------
class SmartRoutingTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(name="J", script_path=self.ok_script)
        self.d = str(self.job.script_log_dir)

    def _set(self, **kw):
        s = NotificationSetting.load()
        for k, v in kw.items():
            setattr(s, k, v)
        s.save()

    def test_alert_on_single_failure_when_threshold_1(self):
        write_run_log(self.d, "J", status="FAILED", started=_ago(minutes=1), fname="a.log")
        with mock.patch("scheduler.services.notifications.send_failure_notification") as f:
            executor._evaluate_notifications(self.job)
        f.assert_called_once()

    def test_no_alert_below_threshold(self):
        self._set(min_consecutive_failures=3)
        write_run_log(self.d, "J", status="SUCCESS", started=_ago(minutes=2), fname="a.log")
        write_run_log(self.d, "J", status="FAILED", started=_ago(minutes=1), fname="b.log")
        with mock.patch("scheduler.services.notifications.send_failure_notification") as f:
            executor._evaluate_notifications(self.job)
        f.assert_not_called()

    def test_alert_when_threshold_reached(self):
        self._set(min_consecutive_failures=2)
        write_run_log(self.d, "J", status="FAILED", started=_ago(minutes=2), fname="a.log")
        write_run_log(self.d, "J", status="FAILED", started=_ago(minutes=1), fname="b.log")
        with mock.patch("scheduler.services.notifications.send_failure_notification") as f:
            executor._evaluate_notifications(self.job)
        f.assert_called_once()

    def test_recovery_notification(self):
        write_run_log(self.d, "J", status="FAILED", started=_ago(minutes=2), fname="a.log")
        write_run_log(self.d, "J", status="SUCCESS", started=_ago(minutes=1), fname="b.log")
        with mock.patch("scheduler.services.notifications.send_recovery_notification") as r:
            executor._evaluate_notifications(self.job)
        r.assert_called_once()

    def test_no_recovery_when_prev_was_success(self):
        write_run_log(self.d, "J", status="SUCCESS", started=_ago(minutes=2), fname="a.log")
        write_run_log(self.d, "J", status="SUCCESS", started=_ago(minutes=1), fname="b.log")
        with mock.patch("scheduler.services.notifications.send_recovery_notification") as r:
            executor._evaluate_notifications(self.job)
        r.assert_not_called()


# ---------------------------------------------------------------------------
#  Notification channels (recovery / missed / email)
# ---------------------------------------------------------------------------
class NotificationChannelTests(ScriptTestCase):
    def _run(self, status="FAILED"):
        from scheduler.services import logreader
        job = Job.objects.create(name="J", script_path=self.ok_script)
        path = write_run_log(str(job.script_log_dir), "J", status=status)
        return logreader.parse_file(path)

    def test_recovery_dispatch_webhook(self):
        s = NotificationSetting.load(); s.webhook_url = "https://hooks.slack.com/x"; s.save()
        run = self._run(status="SUCCESS")
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(notifications.send_recovery_notification(run))

    def test_email_channel(self):
        s = NotificationSetting.load()
        s.email_enabled = True
        s.email_recipients = "ops@x.com, oncall@y.com"
        s.save()
        run = self._run(status="FAILED")
        # Console email backend in tests -> send succeeds without a webhook.
        self.assertTrue(notifications.send_failure_notification(run))

    def test_missed_dispatch(self):
        s = NotificationSetting.load(); s.webhook_url = "https://hooks.slack.com/x"; s.save()
        job = Job.objects.create(name="J", script_path=self.ok_script, cron_expression="0 2 * * *")
        with mock.patch("scheduler.services.notifications.requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(notifications.send_missed_notification(job, _ago(minutes=10)))

    def test_missed_respects_flag(self):
        s = NotificationSetting.load(); s.notify_on_missed = False; s.save()
        job = Job.objects.create(name="J", script_path=self.ok_script, cron_expression="0 2 * * *")
        self.assertFalse(notifications.send_missed_notification(job, _ago(minutes=10)))


# ---------------------------------------------------------------------------
#  Missed-run / heartbeat check
# ---------------------------------------------------------------------------
class MissedRunTests(ScriptTestCase):
    def test_missed_run_alerts_once(self):
        job = Job.objects.create(name="J", script_path=self.ok_script,
                                 cron_expression="* * * * *", grace_period_seconds=0)
        with mock.patch("scheduler.services.notifications.send_missed_notification") as m:
            n1 = sched.check_missed_runs()
            n2 = sched.check_missed_runs()  # second call: already alerted
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        m.assert_called_once()
        job.refresh_from_db()
        self.assertIsNotNone(job.last_missed_alert_for)

    def test_no_alert_when_run_recorded(self):
        job = Job.objects.create(name="J", script_path=self.ok_script,
                                 cron_expression="* * * * *", grace_period_seconds=0)
        # A run that started just now (>= last scheduled minute).
        write_run_log(str(job.script_log_dir), "J", status="SUCCESS", started=_ago(seconds=1))
        with mock.patch("scheduler.services.notifications.send_missed_notification") as m:
            n = sched.check_missed_runs()
        self.assertEqual(n, 0)
        m.assert_not_called()

    def test_inactive_job_skipped(self):
        Job.objects.create(name="J", script_path=self.ok_script,
                           cron_expression="* * * * *", is_active=False, grace_period_seconds=0)
        with mock.patch("scheduler.services.notifications.send_missed_notification") as m:
            self.assertEqual(sched.check_missed_runs(), 0)
        m.assert_not_called()


# ---------------------------------------------------------------------------
#  Trends
# ---------------------------------------------------------------------------
class TrendsTests(ScriptTestCase):
    def test_trends_aggregates(self):
        job = Job.objects.create(name="J", script_path=self.ok_script)
        d = str(job.script_log_dir)
        write_run_log(d, "J", status="SUCCESS", started=_ago(hours=1), fname="a.log",
                      duration=2.0, rss=100.0, cpu_pct=10.0)
        write_run_log(d, "J", status="FAILED", started=_ago(hours=2), fname="b.log",
                      duration=4.0, rss=200.0, cpu_pct=30.0)
        self.client.force_login(make_user("v", role=VIEWER))
        resp = self.client.get(reverse("trends"))
        self.assertEqual(resp.status_code, 200)
        chart = resp.context["chart"]
        self.assertEqual(len(chart["labels"]), 14)
        self.assertEqual(sum(chart["success"]), 1)
        self.assertEqual(sum(chart["failed"]), 1)
        self.assertEqual(max(chart["peak_rss"]), 200.0)

    def test_trends_forbidden(self):
        self.client.force_login(make_user("nobody"))
        self.assertEqual(self.client.get(reverse("trends")).status_code, 404)
