"""views.py — file-based view and RBAC tests."""
from __future__ import annotations

from unittest import mock

from django.urls import reverse

from scheduler.models import Job, NotificationSetting
from scheduler.services import logreader
from scheduler.tests.base import ADMIN, OPERATOR, VIEWER, ScriptTestCase, make_user, write_run_log


class AccessTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("admin", role=ADMIN)
        self.operator = make_user("oper", role=OPERATOR)
        self.viewer = make_user("view", role=VIEWER)
        self.nobody = make_user("nobody")
        self.job = Job.objects.create(name="J", script_path=self.ok_script, is_active=True)

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_viewer_ok(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_dashboard_roleless_forbidden(self):
        self.client.force_login(self.nobody)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_job_list(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("job_list")).status_code, 200)

    def test_job_detail_lists_runs(self):
        write_run_log(str(self.job.script_log_dir), "J", status="SUCCESS")
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_job_create_forbidden_for_operator(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("job_create")).status_code, 403)

    def test_job_create_by_admin(self):
        self.client.force_login(self.admin)
        with mock.patch("scheduler.services.scheduler.sync_jobs"):
            resp = self.client.post(reverse("job_create"), {
                "name": "New", "description": "", "script_path": self.ok_script,
                "working_directory": "", "cron_expression": "0 2 * * *",
                "timeout_seconds": 60, "is_active": "on",
            })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Job.objects.filter(name="New").exists())

    def test_job_delete_by_admin(self):
        self.client.force_login(self.admin)
        with mock.patch("scheduler.services.scheduler.sync_jobs"):
            resp = self.client.post(reverse("job_delete", args=[self.job.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Job.objects.filter(pk=self.job.pk).exists())


class DashboardAggregationTests(ScriptTestCase):
    def test_aggregates_from_files(self):
        viewer = make_user("v", role=VIEWER)
        job = Job.objects.create(name="J", script_path=self.ok_script)
        d = str(job.script_log_dir)
        write_run_log(d, "J", status="SUCCESS", events={"email": 18, "warning": 1},
                      metrics={"emails_sent": 18}, cpu_pct=50.0, rss=100.0, fname="a.log")
        write_run_log(d, "J", status="FAILED", events={"error": 1},
                      metrics={"emails_sent": 5}, cpu_pct=70.0, rss=200.0, fname="b.log")

        self.client.force_login(viewer)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["success_24h"], 1)
        self.assertEqual(resp.context["failed_24h"], 1)
        totals = {m["name"]: m["total"] for m in resp.context["metric_totals"]}
        self.assertEqual(totals["emails_sent"], 23)
        cats = {c["category"]: c["count"] for c in resp.context["event_category_totals"]}
        self.assertEqual(cats["email"], 18)
        self.assertEqual(resp.context["peak_rss_mb"], 200.0)
        self.assertContains(resp, "emails_sent")

    def test_custom_footer_aggregation(self):
        viewer = make_user("v", role=VIEWER)
        job = Job.objects.create(name="J", script_path=self.ok_script)
        d = str(job.script_log_dir)
        write_run_log(d, "J", status="SUCCESS", fname="a.log",
                      footer_extra={"delivery_rate_pct": "80", "env": "prod"})
        write_run_log(d, "J", status="SUCCESS", fname="b.log",
                      footer_extra={"delivery_rate_pct": "100", "env": "prod"})
        self.client.force_login(viewer)
        resp = self.client.get(reverse("dashboard"))
        totals = {f["key"]: f for f in resp.context["custom_footer_totals"]}
        # Numeric field is aggregated.
        self.assertEqual(totals["delivery_rate_pct"]["avg"], 90.0)
        self.assertEqual(totals["delivery_rate_pct"]["total"], 180.0)
        self.assertEqual(totals["delivery_rate_pct"]["count"], 2)
        # Non-numeric custom field (env=prod) is not included in aggregation.
        self.assertNotIn("env", totals)
        self.assertContains(resp, "delivery_rate_pct")


class LogViewTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        self.viewer = make_user("v", role=VIEWER)
        self.job = Job.objects.create(name="J", script_path=self.ok_script)

    def test_log_list(self):
        write_run_log(str(self.job.script_log_dir), "J", status="SUCCESS")
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("log_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "J")

    def test_log_list_filter_status(self):
        d = str(self.job.script_log_dir)
        write_run_log(d, "J", status="SUCCESS", fname="ok.log")
        write_run_log(d, "J", status="FAILED", fname="bad.log")
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("log_list"), {"status": "FAILED"})
        self.assertEqual(len(resp.context["runs"]), 1)

    def test_log_detail_by_token(self):
        path = write_run_log(str(self.job.script_log_dir), "J", status="SUCCESS",
                             body=["2026-06-11 09:00:00.001  EVENT   [email] To: a@b.com"])
        token = logreader.encode_token(path)
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("log_detail", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "To: a@b.com")

    def test_log_detail_bad_token_404(self):
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("log_detail", args=["bogus"]))
        self.assertEqual(resp.status_code, 404)

    def test_log_list_forbidden(self):
        self.client.force_login(make_user("nobody"))
        self.assertEqual(self.client.get(reverse("log_list")).status_code, 404)

    def test_log_detail_forbidden(self):
        path = write_run_log(str(self.job.script_log_dir), "J")
        token = logreader.encode_token(path)
        self.client.force_login(make_user("nobody2"))
        self.assertEqual(self.client.get(reverse("log_detail", args=[token])).status_code, 404)

    def test_log_list_filter_by_job(self):
        write_run_log(str(self.job.script_log_dir), "J", status="SUCCESS")
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse("log_list"), {"job": str(self.job.pk)})
        self.assertEqual(resp.status_code, 200)


class RunNowTests(ScriptTestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("admin", role=ADMIN)
        self.viewer = make_user("view", role=VIEWER)
        self.job = Job.objects.create(name="J", script_path=self.ok_script, is_active=True)

    def test_viewer_cannot_run(self):
        self.client.force_login(self.viewer)
        with mock.patch("scheduler.services.executor.run_job_async") as run:
            self.client.post(reverse("job_run", args=[self.job.pk]))
        run.assert_not_called()

    def test_admin_runs(self):
        self.client.force_login(self.admin)
        with mock.patch("scheduler.services.executor.run_job_async") as run:
            resp = self.client.post(reverse("job_run", args=[self.job.pk]))
        run.assert_called_once()
        self.assertEqual(resp.status_code, 302)

    def test_already_running(self):
        self.client.force_login(self.admin)
        with mock.patch("scheduler.services.executor.run_job_async",
                        side_effect=__import__("scheduler.services.executor", fromlist=["x"]).JobAlreadyRunningError("x")):
            resp = self.client.post(reverse("job_run", args=[self.job.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_get_not_allowed(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("job_run", args=[self.job.pk])).status_code, 405)


class StatusApiTests(ScriptTestCase):
    def test_status_api(self):
        viewer = make_user("v", role=VIEWER)
        job = Job.objects.create(name="J", script_path=self.ok_script, is_active=True)
        write_run_log(str(job.script_log_dir), "J", status="SUCCESS")
        self.client.force_login(viewer)
        data = self.client.get(reverse("job_status_api")).json()
        self.assertIn(str(job.pk), data["jobs"])
        self.assertEqual(data["jobs"][str(job.pk)]["status"], "SUCCESS")

    def test_status_api_forbidden(self):
        self.client.force_login(make_user("nobody"))
        self.assertEqual(self.client.get(reverse("job_status_api")).status_code, 403)


class DuplicateAndSettingsTests(ScriptTestCase):
    def test_duplicate(self):
        admin = make_user("admin", role=ADMIN)
        job = Job.objects.create(name="Orig", script_path=self.ok_script)
        self.client.force_login(admin)
        resp = self.client.post(reverse("job_duplicate", args=[job.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Job.objects.filter(name="Orig (copy)").exists())

    def test_settings_admin(self):
        admin = make_user("admin", role=ADMIN)
        self.client.force_login(admin)
        resp = self.client.post(reverse("settings"), {
            "provider": "SLACK", "webhook_url": "https://hooks.slack.com/x",
            "notify_on_failure": "on", "notify_on_timeout": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(NotificationSetting.load().webhook_url, "https://hooks.slack.com/x")

    def test_settings_operator_forbidden(self):
        self.client.force_login(make_user("op", role=OPERATOR))
        self.assertEqual(self.client.get(reverse("settings")).status_code, 403)
