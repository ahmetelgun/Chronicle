"""
RBAC — role-based access control helpers.

Roles are modeled as Django Groups (Admin / Operator / Viewer) and are mapped
from LDAP groups in signals.py. The mixins here are used in views.

Permission matrix:
                 View        Run Now   Add/Edit/Delete    Settings
  Admin              ✓          ✓             ✓              ✓
  Operator           ✓          ✓             ✗              ✗
  Viewer             ✓          ✗             ✗              ✗
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.models import User


def user_in_role(user: User, *roles: str) -> bool:
    """Does the user have one of the given roles? (superuser is always True)"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def can_view(user: User) -> bool:
    return user_in_role(
        user, settings.ROLE_ADMIN, settings.ROLE_OPERATOR, settings.ROLE_VIEWER
    )


def can_run(user: User) -> bool:
    """Run Now permission: Admin or Operator."""
    return user_in_role(user, settings.ROLE_ADMIN, settings.ROLE_OPERATOR)


def can_manage(user: User) -> bool:
    """Add/Edit/Delete and Settings permission: Admin only."""
    return user_in_role(user, settings.ROLE_ADMIN)


class ViewerRequiredMixin(UserPassesTestMixin):
    """Minimum permission to view lists and logs (all three roles)."""

    def test_func(self) -> bool:
        return can_view(self.request.user)


class OperatorRequiredMixin(UserPassesTestMixin):
    """For Run Now: Admin or Operator."""

    def test_func(self) -> bool:
        return can_run(self.request.user)


class AdminRequiredMixin(UserPassesTestMixin):
    """For administrative operations: Admin only."""

    def test_func(self) -> bool:
        return can_manage(self.request.user)
