"""
Data models.

  Job                -> A managed Linux script + schedule definition
  NotificationSetting-> Singleton system settings such as a Slack/Teams webhook

NOTE: Execution logs are NO LONGER STORED IN THE DATABASE. Each run writes its own
.log file into the logs/ folder in the script's directory (via the script-side
job_logger). Listings/dashboard scan these files (see services.logreader); this way
non-scheduler (independent) runs are visible too.

Known severity levels (for UI coloring; the event category is not limited to these).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

try:
    from croniter import croniter
except ImportError:  # validation is skipped if croniter is not installed
    croniter = None


class Job(models.Model):
    """Represents a script on the server along with its run/schedule metadata."""

    name = models.CharField("Script Name", max_length=150, unique=True)
    description = models.TextField("Description", blank=True)

    # Full path of the script to run, e.g.: /opt/scripts/backup.sh
    script_path = models.CharField("Script File Path", max_length=500)

    # Working directory (CWD). If empty, the script's own directory is used.
    working_directory = models.CharField(
        "Working Directory (CWD)", max_length=500, blank=True
    )

    # Standard cron expression: minute hour day month day-of-week  (e.g.: 0 2 * * *)
    cron_expression = models.CharField(
        "Cron Schedule",
        max_length=100,
        blank=True,
        help_text="Standard cron syntax, e.g.: 0 2 * * *  (if left empty, it is not scheduled automatically)",
    )

    # Timeout in seconds. If the time runs out, the process is killed and counted as a "Timeout".
    timeout_seconds = models.PositiveIntegerField("Timeout (s)", default=3600)

    is_active = models.BooleanField("Active", default=True)

    # Static per-job environment variables, merged into the sanitized run env.
    # {"KEY": "value", ...}
    env_vars = models.JSONField("Environment variables", default=dict, blank=True)

    # Run-time parameter definitions filled in on "Run Now". Each item:
    #   {"name": "TARGET", "default": "", "required": false, "label": "Target host"}
    # Submitted values are passed to the run as environment variables.
    run_parameters = models.JSONField("Run parameters", default=list, blank=True)

    # Missed-run / heartbeat detection: how long (seconds) after a scheduled time to
    # wait before declaring the run "missed".
    grace_period_seconds = models.PositiveIntegerField("Grace period (s)", default=300)
    # The scheduled time we last alerted about as missed (avoids duplicate alerts).
    last_missed_alert_for = models.DateTimeField(null=True, blank=True, editable=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_jobs",
        verbose_name="Created by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("job_detail", args=[self.pk])

    @property
    def is_scheduled(self) -> bool:
        """Is a cron expression defined and the script active?"""
        return bool(self.cron_expression.strip()) and self.is_active

    @property
    def script_log_dir(self):
        """Directory containing this job's log files: <script_dir>/logs/."""
        from pathlib import Path
        return Path(self.script_path).resolve().parent / settings.LOG_DIRNAME

    @property
    def last_execution(self):
        """The most recent run (read from the log file) or None."""
        from scheduler.services import logreader
        runs = logreader.list_runs_for_job(self)
        return runs[0] if runs else None

    @property
    def is_running(self) -> bool:
        """Is there a run currently in progress? (a .log file without a footer, or a .lock)"""
        from scheduler.services import logreader
        return logreader.is_job_running(self)

    def next_run_time(self):
        """Returns the next run time based on the cron expression."""
        if not self.is_scheduled or croniter is None:
            return None
        try:
            base = timezone.localtime()
            itr = croniter(self.cron_expression, base)
            return itr.get_next(type(base))
        except (ValueError, KeyError):
            return None

    # Name length limit (must match the name field's max_length).
    _NAME_MAX = 150

    @staticmethod
    def unique_copy_name(base_name: str) -> str:
        """
        Produces a unique, non-colliding name in the form '<base> (copy)'.
        If it already exists, increments as '(copy 2)', '(copy 3)' ...
        The name is truncated to fit within the name field's max_length limit.
        """
        def fit(base: str, suffix: str) -> str:
            room = Job._NAME_MAX - len(suffix)
            return f"{base[:room].rstrip()}{suffix}"

        candidate = fit(base_name, " (copy)")
        i = 2
        while Job.objects.filter(name=candidate).exists():
            candidate = fit(base_name, f" (copy {i})")
            i += 1
        return candidate

    def duplicate(self, *, created_by=None, activate: bool = False) -> "Job":
        """
        Creates and saves a copy of this job.

        * All configuration fields are copied; execution logs are NOT copied —
          the copy starts with a clean history.
        * For safety, it is created inactive by default (activate=False), so that
          duplicating an active/cron-scheduled job does not accidentally create double scheduling.
        """
        clone = Job(
            name=self.unique_copy_name(self.name),
            description=self.description,
            script_path=self.script_path,
            working_directory=self.working_directory,
            cron_expression=self.cron_expression,
            timeout_seconds=self.timeout_seconds,
            is_active=activate,
            created_by=created_by,
        )
        clone.save()
        return clone


class NotificationSetting(models.Model):
    """
    Singleton system setting: notification webhook configuration.
    Only a single record is kept (pk=1).
    """

    class Provider(models.TextChoices):
        SLACK = "SLACK", "Slack"
        TEAMS = "TEAMS", "Microsoft Teams"

    provider = models.CharField(
        max_length=10, choices=Provider.choices, default=Provider.SLACK
    )
    webhook_url = models.URLField("Webhook URL", max_length=1000, blank=True)
    notify_on_failure = models.BooleanField(
        "Notify on failure", default=True
    )
    notify_on_timeout = models.BooleanField(
        "Notify on timeout", default=True
    )

    # --- Email channel (SMTP config comes from Django settings / env) ---
    email_enabled = models.BooleanField("Send email alerts", default=False)
    email_recipients = models.CharField(
        "Email recipients", max_length=1000, blank=True,
        help_text="Comma-separated email addresses.",
    )

    # --- Smart routing ---
    # Only alert once this many consecutive failures have occurred (1 = every failure).
    min_consecutive_failures = models.PositiveIntegerField(
        "Alert after N consecutive failures", default=1
    )
    # Send a "recovered" notification when a job goes back to success after failing.
    notify_on_recovery = models.BooleanField("Notify on recovery", default=True)
    # Send an alert when a scheduled run is missed (heartbeat).
    notify_on_missed = models.BooleanField("Notify on missed run", default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Setting"
        verbose_name_plural = "Notification Settings"

    def __str__(self) -> str:
        return f"{self.get_provider_display()} notification setting"

    @classmethod
    def load(cls) -> "NotificationSetting":
        """Fetch the singleton record; create it if it does not exist."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1  # always a single record
        super().save(*args, **kwargs)


# NOTE: The old JobMetric / JobEvent tables were removed. Metrics and events are no
# longer written to the DB; they are kept as lines in each execution's .log file, and
# the summary counts are stored in the JobExecutionLog.event_summary / metric_summary fields.

# Known severity levels (for UI coloring; the event category is not limited to these).
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
