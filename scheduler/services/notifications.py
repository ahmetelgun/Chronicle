"""
Notification (Alerting) service.

Multi-channel: Slack/Teams webhook + email. Three notification types:
  * failure  — a run finished as Failed/Timeout/Aborted
  * recovery — a job went back to success after failing
  * missed   — a scheduled run did not happen within its grace period (heartbeat)

Smart routing (consecutive-failure threshold, recovery detection) is decided by
the caller (executor); this module performs the actual delivery.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

from scheduler.models import NotificationSetting

logger = logging.getLogger("scheduler")

_WEBHOOK_TIMEOUT = 10
_LOG_PREVIEW_CHARS = 200


# ---------------------------------------------------------------------------
#  Channel delivery
# ---------------------------------------------------------------------------
def _build_webhook_payload(setting, *, title, color, fields, body) -> dict:
    """Builds a Slack (Block Kit) or Teams (MessageCard) payload."""
    if setting.provider == NotificationSetting.Provider.TEAMS:
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": title,
            "title": title,
            "sections": [{
                "facts": [{"name": k, "value": str(v)} for k, v in fields],
                "text": f"```\n{body}\n```" if body else "",
            }],
        }
    return {
        "text": title,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*{k}:*\n{v}"} for k, v in fields
            ]},
            *([{"type": "section", "text": {"type": "mrkdwn", "text": f"```{body}```"}}]
              if body else []),
        ],
    }


def _send_webhook(setting, payload) -> bool:
    if not setting.webhook_url:
        return False
    try:
        resp = requests.post(setting.webhook_url, json=payload, timeout=_WEBHOOK_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Webhook notification failed: %s", exc)
        return False


def _send_email(setting, subject, body) -> bool:
    recipients = [a.strip() for a in setting.email_recipients.split(",") if a.strip()]
    if not (setting.email_enabled and recipients):
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients,
                  fail_silently=False)
        return True
    except Exception as exc:  # pragma: no cover - SMTP errors must not break the flow
        logger.error("Email notification failed: %s", exc)
        return False


def _dispatch(setting, *, title, color, fields, body) -> bool:
    """Fan out to all configured channels. Returns True if any channel delivered."""
    payload = _build_webhook_payload(
        setting, title=title, color=color, fields=fields, body=body
    )
    sent_webhook = _send_webhook(setting, payload)

    email_body = "\n".join(f"{k}: {v}" for k, v in fields)
    if body:
        email_body += f"\n\n{body}"
    sent_email = _send_email(setting, f"[Chronicle] {title}", email_body)

    if sent_webhook or sent_email:
        logger.info("Notification sent: %s", title)
    return sent_webhook or sent_email


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def _error_preview(run) -> str:
    """Produces a short preview from the ERROR/ERR lines in the run's log file."""
    from scheduler.services import logreader

    _, lines = logreader.parse_full(run.path)
    errs = [msg for _ts, level, msg in lines if level in ("ERROR", "ERR") and msg.strip()]
    if errs:
        return " | ".join(errs)[:_LOG_PREVIEW_CHARS]
    tail = [msg for _ts, _lvl, msg in lines[-3:]]
    return (" | ".join(tail) or "(no output)")[:_LOG_PREVIEW_CHARS]


def _run_time(run) -> str:
    return run.started.strftime("%Y-%m-%d %H:%M:%S UTC") if run.started else "-"


# ---------------------------------------------------------------------------
#  Notification types
# ---------------------------------------------------------------------------
def send_failure_notification(run) -> bool:
    """Sends a failure alert for a failed Run. Never raises."""
    setting = NotificationSetting.load()
    is_timeout = run.status == "TIMEOUT"
    if is_timeout and not setting.notify_on_timeout:
        return False
    if not is_timeout and not setting.notify_on_failure:
        return False

    fields = [
        ("Script", run.job_name),
        ("Status", run.status_display),
        ("Triggered", _run_time(run)),
        ("Exit Code", run.exit_code),
        ("Triggered by", run.trigger_display),
    ]
    return _dispatch(setting, title="🚨 Critical Script Failure", color="D32F2F",
                     fields=fields, body=_error_preview(run))


def send_recovery_notification(run) -> bool:
    """Sends a 'recovered' alert when a job returns to success after failing."""
    setting = NotificationSetting.load()
    if not setting.notify_on_recovery:
        return False
    fields = [
        ("Script", run.job_name),
        ("Status", run.status_display),
        ("Triggered", _run_time(run)),
        ("Triggered by", run.trigger_display),
    ]
    return _dispatch(setting, title="✅ Recovered", color="2E7D32",
                     fields=fields, body="The job is back to success after previous failure(s).")


def send_missed_notification(job, expected_time) -> bool:
    """Sends an alert when a scheduled run did not happen (heartbeat)."""
    setting = NotificationSetting.load()
    if not setting.notify_on_missed:
        return False
    expected = expected_time.strftime("%Y-%m-%d %H:%M:%S %Z") if expected_time else "-"
    fields = [
        ("Script", job.name),
        ("Expected at", expected),
        ("Schedule", job.cron_expression or "-"),
    ]
    return _dispatch(setting, title="⏰ Missed Scheduled Run", color="F9A825",
                     fields=fields, body="No run was recorded for the scheduled time.")
