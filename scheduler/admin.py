"""Django admin registrations (accessible to the Admin LDAP group).

NOTE: Since execution logs are now kept in files rather than the DB, only Job and
NotificationSetting appear in the admin.
"""
from django.contrib import admin

from scheduler.models import Job, NotificationSetting


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("name", "script_path", "cron_expression", "is_active", "created_by")
    list_filter = ("is_active",)
    search_fields = ("name", "script_path")
    readonly_fields = ("created_at", "updated_at")


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    list_display = ("provider", "webhook_url", "notify_on_failure", "notify_on_timeout")
