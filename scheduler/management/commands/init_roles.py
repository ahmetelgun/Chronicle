"""
Management command that creates the RBAC roles (Django Groups).

    python manage.py init_roles

When LDAP is disabled or during initial setup, this creates the
Admin/Operator/Viewer groups and assigns the appropriate model permissions to
each group. This way local test users can also be added to these groups and
tested on a role basis.
"""
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from scheduler.models import Job, NotificationSetting


class Command(BaseCommand):
    help = "Creates the Admin/Operator/Viewer roles and their permissions."

    def handle(self, *args, **options):
        roles = [settings.ROLE_ADMIN, settings.ROLE_OPERATOR, settings.ROLE_VIEWER]
        groups = {}
        for role in roles:
            group, created = Group.objects.get_or_create(name=role)
            groups[role] = group
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if created else 'Exists'}: {role}")
            )

        # Collect permissions (execution logs are now in files; no model permission).
        job_ct = ContentType.objects.get_for_model(Job)
        setting_ct = ContentType.objects.get_for_model(NotificationSetting)

        all_perms = Permission.objects.filter(
            content_type__in=[job_ct, setting_ct]
        )
        view_perms = all_perms.filter(codename__startswith="view")

        # Admin: all permissions.
        groups[settings.ROLE_ADMIN].permissions.set(all_perms)
        # Operator: view permissions (Run Now check is in the view layer).
        groups[settings.ROLE_OPERATOR].permissions.set(view_perms)
        # Viewer: view only.
        groups[settings.ROLE_VIEWER].permissions.set(view_perms)

        self.stdout.write(self.style.SUCCESS("Roles and permissions are ready."))
