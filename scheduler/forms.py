"""Forms — adding/editing Jobs and notification settings."""
from __future__ import annotations

import re

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
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_env_text(text: str) -> dict:
    """Parses 'KEY=value' lines into a dict. Raises ValidationError on bad keys."""
    env = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise forms.ValidationError(f"Each line must be 'KEY=value': {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _NAME_RE.match(key):
            raise forms.ValidationError(f"Invalid env var name: {key!r}")
        env[key] = value.strip()
    return env


def _parse_params_text(text: str) -> list:
    """Parses 'NAME' or 'NAME=default' lines into a parameter spec list."""
    params = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, default = line.partition("=")
        name = name.strip()
        if not _NAME_RE.match(name):
            raise forms.ValidationError(f"Invalid parameter name: {name!r}")
        params.append({"name": name, "default": default.strip(), "label": name})
    return params


class JobForm(forms.ModelForm):
    """Script add/edit form (Admin only)."""

    env_vars_text = forms.CharField(
        label="Environment variables", required=False,
        widget=forms.Textarea(attrs={
            "class": _TEXTAREA, "rows": 3,
            "placeholder": "KEY=value (one per line)\nAPI_URL=https://api.company.local",
        }),
        help_text="Static env vars passed to every run (KEY=value per line).",
    )
    run_parameters_text = forms.CharField(
        label="Run parameters", required=False,
        widget=forms.Textarea(attrs={
            "class": _TEXTAREA, "rows": 3,
            "placeholder": "NAME or NAME=default (one per line)\nTARGET_HOST=localhost",
        }),
        help_text="Prompted on 'Run Now' and passed as env vars.",
    )

    class Meta:
        model = Job
        fields = [
            "name",
            "description",
            "script_path",
            "working_directory",
            "cron_expression",
            "timeout_seconds",
            "grace_period_seconds",
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
            "grace_period_seconds": forms.NumberInput(attrs={"class": _INPUT, "min": 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["env_vars_text"].initial = "\n".join(
                f"{k}={v}" for k, v in (self.instance.env_vars or {}).items()
            )
            self.fields["run_parameters_text"].initial = "\n".join(
                p["name"] + (f"={p.get('default','')}" if p.get("default") else "")
                for p in (self.instance.run_parameters or [])
            )

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

    def clean_env_vars_text(self) -> dict:
        return _parse_env_text(self.cleaned_data.get("env_vars_text", ""))

    def clean_run_parameters_text(self) -> list:
        return _parse_params_text(self.cleaned_data.get("run_parameters_text", ""))

    def save(self, commit=True):
        self.instance.env_vars = self.cleaned_data.get("env_vars_text") or {}
        self.instance.run_parameters = self.cleaned_data.get("run_parameters_text") or []
        return super().save(commit)


class NotificationSettingForm(forms.ModelForm):
    """Notification channel + routing settings form (Admin only)."""

    class Meta:
        model = NotificationSetting
        fields = [
            "provider",
            "webhook_url",
            "notify_on_failure",
            "notify_on_timeout",
            "email_enabled",
            "email_recipients",
            "min_consecutive_failures",
            "notify_on_recovery",
            "notify_on_missed",
        ]
        widgets = {
            "provider": forms.Select(attrs={"class": _SELECT}),
            "webhook_url": forms.URLInput(
                attrs={"class": _INPUT, "placeholder": "https://hooks.slack.com/services/..."}
            ),
            "email_recipients": forms.TextInput(
                attrs={"class": _INPUT, "placeholder": "ops@company.local, oncall@company.local"}
            ),
            "min_consecutive_failures": forms.NumberInput(attrs={"class": _INPUT, "min": 1}),
        }
