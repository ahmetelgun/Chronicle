"""Forms — adding/editing Jobs and notification settings."""
from __future__ import annotations

from django import forms

from scheduler.models import Job, NotificationSetting

try:
    from croniter import croniter
except ImportError:
    croniter = None


# Helper for applying Bulma CSS form classes to each widget.
_INPUT = "input"
_TEXTAREA = "textarea"
_SELECT = "select"


class JobForm(forms.ModelForm):
    """Script add/edit form (Admin only)."""

    class Meta:
        model = Job
        fields = [
            "name",
            "description",
            "script_path",
            "working_directory",
            "cron_expression",
            "timeout_seconds",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT, "placeholder": "Nightly Backup"}),
            "description": forms.Textarea(
                attrs={"class": _TEXTAREA, "rows": 2, "placeholder": "Short description (optional)"}
            ),
            "script_path": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "/opt/scripts/backup.sh"}
            ),
            "working_directory": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "/opt/scripts (if empty, the script's directory)"}
            ),
            "cron_expression": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "0 2 * * *"}
            ),
            "timeout_seconds": forms.NumberInput(attrs={"class": _INPUT, "min": 1}),
        }

    def clean_cron_expression(self) -> str:
        """Validate the cron expression (can be left empty = not scheduled automatically)."""
        expr = (self.cleaned_data.get("cron_expression") or "").strip()
        if not expr:
            return ""
        if croniter is None:
            return expr  # if the validation library is missing, accept it as-is
        if not croniter.is_valid(expr):
            raise forms.ValidationError(
                "Invalid cron expression. Example: '0 2 * * *' (every day at 02:00)."
            )
        return expr

    def clean_timeout_seconds(self) -> int:
        value = self.cleaned_data.get("timeout_seconds") or 0
        if value < 1:
            raise forms.ValidationError("The timeout must be at least 1 second.")
        if value > 86400:
            raise forms.ValidationError("The timeout cannot exceed 24 hours (86400 s).")
        return value


class NotificationSettingForm(forms.ModelForm):
    """Slack/Teams webhook settings form (Admin only)."""

    class Meta:
        model = NotificationSetting
        fields = [
            "provider",
            "webhook_url",
            "notify_on_failure",
            "notify_on_timeout",
        ]
        widgets = {
            "provider": forms.Select(attrs={"class": _SELECT}),
            "webhook_url": forms.URLInput(
                attrs={"class": _INPUT, "placeholder": "https://hooks.slack.com/services/..."}
            ),
        }
