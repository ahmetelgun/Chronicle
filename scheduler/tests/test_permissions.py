"""permissions.py (RBAC) tests."""
from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from scheduler import permissions as perms
from scheduler.tests.base import ADMIN, OPERATOR, VIEWER, make_user


class RoleHelperTests(TestCase):
    def test_anonymous_has_nothing(self):
        anon = AnonymousUser()
        self.assertFalse(perms.can_view(anon))
        self.assertFalse(perms.can_run(anon))
        self.assertFalse(perms.can_manage(anon))

    def test_superuser_has_everything(self):
        su = make_user("root", superuser=True)
        self.assertTrue(perms.can_view(su))
        self.assertTrue(perms.can_run(su))
        self.assertTrue(perms.can_manage(su))

    def test_admin_role(self):
        u = make_user("a", role=ADMIN)
        self.assertTrue(perms.can_view(u))
        self.assertTrue(perms.can_run(u))
        self.assertTrue(perms.can_manage(u))

    def test_operator_role(self):
        u = make_user("o", role=OPERATOR)
        self.assertTrue(perms.can_view(u))
        self.assertTrue(perms.can_run(u))
        self.assertFalse(perms.can_manage(u))

    def test_viewer_role(self):
        u = make_user("v", role=VIEWER)
        self.assertTrue(perms.can_view(u))
        self.assertFalse(perms.can_run(u))
        self.assertFalse(perms.can_manage(u))

    def test_no_role(self):
        u = make_user("nobody")
        self.assertFalse(perms.can_view(u))
        self.assertFalse(perms.can_run(u))
        self.assertFalse(perms.can_manage(u))

    def test_user_in_role_multiple(self):
        u = make_user("o", role=OPERATOR)
        self.assertTrue(perms.user_in_role(u, ADMIN, OPERATOR))
        self.assertFalse(perms.user_in_role(u, ADMIN, VIEWER))
