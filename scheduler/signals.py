"""
LDAP -> Django RBAC mapping signals.

django-auth-ldap sends the `populate_user` signal when a user is authenticated.
At that point we look at the user's LDAP group memberships and add or remove
them from the correct Django Group (Admin/Operator/Viewer).

The core mapping logic (`map_groups_to_roles`) is a pure function independent of
LDAP, so it can be tested without python-ldap. The receiver is connected only when
LDAP is enabled and calls this function.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.contrib.auth.models import Group

logger = logging.getLogger("scheduler")


def map_groups_to_roles(user, group_dns: Iterable[str]) -> set[str]:
    """
    Maps the user's LDAP group DNs to Django roles (Groups).

    settings.AUTH_LDAP_GROUP_MAPPING: { ldap_dn: django_group_name }
    Only adds/removes the roles managed in this mapping; it does not disturb
    other groups (e.g. manually assigned ones).

    Returns: the set of role names assigned to the user.
    """
    user_group_dns = {dn.lower() for dn in group_dns}
    mapping = getattr(settings, "AUTH_LDAP_GROUP_MAPPING", {})

    assigned_roles = {
        role_name
        for ldap_dn, role_name in mapping.items()
        if ldap_dn.lower() in user_group_dns
    }

    # The user must be saved before an M2M assignment.
    if user.pk is None:
        user.save()

    for role_name in set(mapping.values()):
        group, _ = Group.objects.get_or_create(name=role_name)
        if role_name in assigned_roles:
            user.groups.add(group)
        else:
            user.groups.remove(group)

    logger.info(
        "LDAP role mapping: %s -> %s",
        user.get_username(),
        sorted(assigned_roles) or "(no roles)",
    )
    return assigned_roles


# If LDAP integration is disabled, there is no need to connect the signal.
if getattr(settings, "LDAP_ENABLED", False):  # pragma: no cover - requires python-ldap
    from django.dispatch import receiver
    from django_auth_ldap.backend import populate_user

    @receiver(populate_user)
    def _on_populate_user(sender, user=None, ldap_user=None, **kwargs):
        """django-auth-ldap populate_user signal -> role mapping."""
        if user is None or ldap_user is None:
            return
        map_groups_to_roles(user, ldap_user.group_dns)
