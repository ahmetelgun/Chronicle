"""templatetags, signals (pure function), apps and management command tests."""
from __future__ import annotations

from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from scheduler.templatetags.scheduler_extras import (
    duration_human,
    event_class,
    level_class,
    status_class,
)
from scheduler.tests.base import ADMIN, OPERATOR, VIEWER, make_user


class TemplateTagTests(TestCase):
    def test_status_class_known(self):
        self.assertEqual(status_class("SUCCESS"), "is-success")
        self.assertEqual(status_class("FAILED"), "is-danger")
        self.assertEqual(status_class("TIMEOUT"), "is-warning")
        self.assertEqual(status_class("RUNNING"), "is-info")

    def test_status_class_unknown(self):
        self.assertEqual(status_class("WTF"), "is-light")

    def test_level_class(self):
        self.assertEqual(level_class("ERROR"), "is-danger")
        self.assertEqual(level_class("WARN"), "is-warning")
        self.assertEqual(level_class("METRIC"), "is-link")
        self.assertEqual(level_class("EVENT"), "is-info")
        self.assertEqual(level_class("OUT"), "is-light")
        self.assertEqual(level_class("???"), "is-light")

    def test_status_class_aborted(self):
        self.assertEqual(status_class("ABORTED"), "is-warning")

    def test_event_class(self):
        # Known severity levels get a specific color
        self.assertEqual(event_class("error"), "is-danger")
        self.assertEqual(event_class("warning"), "is-warning")
        self.assertEqual(event_class("info"), "is-light")
        # Free-form categories get a neutral color
        self.assertEqual(event_class("email"), "is-info")
        self.assertEqual(event_class("payment"), "is-info")
        self.assertEqual(event_class(""), "is-info")

    def test_duration_human(self):
        self.assertEqual(duration_human(None), "—")
        self.assertEqual(duration_human("bad"), "—")
        self.assertEqual(duration_human(0.25), "250 ms")
        self.assertEqual(duration_human(5), "5s")
        self.assertEqual(duration_human(65), "1m 5s")
        self.assertEqual(duration_human(3725), "1h 2m 5s")


class SignalMappingTests(TestCase):
    """signals.map_groups_to_roles pure function test (does not require python-ldap)."""

    def test_maps_admin_group(self):
        from django.conf import settings
        from scheduler.signals import map_groups_to_roles

        user = make_user("ldapuser")
        roles = map_groups_to_roles(user, [settings.LDAP_GROUP_ADMIN])
        self.assertIn(ADMIN, roles)
        self.assertTrue(user.groups.filter(name=ADMIN).exists())

    def test_removes_role_when_not_in_group(self):
        from django.conf import settings
        from scheduler.signals import map_groups_to_roles

        user = make_user("ldapuser", role=ADMIN)
        # No longer in any LDAP group -> Admin role should be removed
        roles = map_groups_to_roles(user, [])
        self.assertEqual(roles, set())
        self.assertFalse(user.groups.filter(name=ADMIN).exists())

    def test_multiple_groups(self):
        from django.conf import settings
        from scheduler.signals import map_groups_to_roles

        user = make_user("multi")
        roles = map_groups_to_roles(
            user, [settings.LDAP_GROUP_OPERATOR, settings.LDAP_GROUP_VIEWER]
        )
        self.assertEqual(roles, {OPERATOR, VIEWER})


class InitRolesCommandTests(TestCase):
    def test_creates_roles(self):
        Group.objects.all().delete()
        out = StringIO()
        call_command("init_roles", stdout=out)
        for role in (ADMIN, OPERATOR, VIEWER):
            self.assertTrue(Group.objects.filter(name=role).exists())
        # The Admin group should have permissions
        admin = Group.objects.get(name=ADMIN)
        self.assertTrue(admin.permissions.exists())


class SeedDemoCommandTests(TestCase):
    def test_creates_demo_jobs(self):
        from scheduler.models import Job
        out = StringIO()
        call_command("seed_demo", stdout=out, stderr=StringIO())
        # At least a few known demo jobs should be created
        self.assertTrue(Job.objects.filter(name="Hello World").exists())
        self.assertGreaterEqual(Job.objects.count(), 8)

    def test_idempotent_skips_existing(self):
        from scheduler.models import Job
        call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
        count = Job.objects.count()
        # Second time (without force) -> no new records should be added
        call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Job.objects.count(), count)

    def test_force_updates_existing(self):
        from scheduler.models import Job
        call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
        job = Job.objects.get(name="Hello World")
        job.timeout_seconds = 9999
        job.save()
        # With force, defaults should be written back
        call_command("seed_demo", "--force", stdout=StringIO(), stderr=StringIO())
        job.refresh_from_db()
        self.assertEqual(job.timeout_seconds, 30)


class AppConfigTests(TestCase):
    def test_should_start_scheduler_logic(self):
        from scheduler.apps import SchedulerConfig
        import sys

        orig = sys.argv
        try:
            # manage.py migrate -> do not start
            sys.argv = ["manage.py", "migrate"]
            self.assertFalse(SchedulerConfig._should_start_scheduler())
            # manage.py test -> do not start
            sys.argv = ["manage.py", "test"]
            self.assertFalse(SchedulerConfig._should_start_scheduler())
            # gunicorn (not manage.py) -> start
            sys.argv = ["gunicorn", "chronicle.wsgi"]
            self.assertTrue(SchedulerConfig._should_start_scheduler())
        finally:
            sys.argv = orig
