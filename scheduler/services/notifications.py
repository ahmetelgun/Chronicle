"""
Notification (Alerting) service.

When a run finishes as "Failed"/"Timeout"/"Aborted", it sends a critical-error
notification to the configured Slack/Teams webhook. The input is a Run object
parsed from a file (see services.logreader).
"""
from __future__ import annotations

import logging

import requests

from scheduler.models import NotificationSetting

logger = logging.getLogger("scheduler")

_WEBHOOK_TIMEOUT = 10
_LOG_PREVIEW_CHARS = 200


def _error_preview(run) -> str:
    """Produces a short preview from the ERROR/ERR lines in the run's log file."""
    from scheduler.services import logreader

    _, lines = logreader.parse_full(run.path)
    errs = [msg for _ts, level, msg in lines if level in ("ERROR", "ERR") and msg.strip()]
    if errs:
        return " | ".join(errs)[:_LOG_PREVIEW_CHARS]
    # If there are no error lines, use the last few lines.
    tail = [msg for _ts, _lvl, msg in lines[-3:]]
    return (" | ".join(tail) or "(no output)")[:_LOG_PREVIEW_CHARS]


def _build_slack_payload(run, error_preview: str) -> dict:
    triggered = run.started.strftime("%Y-%m-%d %H:%M:%S UTC") if run.started else "-"
    return {
        "text": f":rotating_light: Script Failure: {run.job_name}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "🚨 Critical Script Failure"}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Script:*\n{run.job_name}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{run.status_display}"},
                {"type": "mrkdwn", "text": f"*Triggered:*\n{triggered}"},
                {"type": "mrkdwn", "text": f"*Exit Code:*\n{run.exit_code}"},
                {"type": "mrkdwn", "text": f"*Triggered by:*\n{run.trigger_display}"},
            ]},
            {"type": "section", "text": {"type": "mrkdwn",
                "text": f"*Error Log (first {_LOG_PREVIEW_CHARS} chars):*\n```{error_preview}```"}},
        ],
    }


def _build_teams_payload(run, error_preview: str) -> dict:
    triggered = run.started.strftime("%Y-%m-%d %H:%M:%S UTC") if run.started else "-"
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "D32F2F",
        "summary": f"Script Failure: {run.job_name}",
        "title": "🚨 Critical Script Failure",
        "sections": [{
            "facts": [
                {"name": "Script", "value": run.job_name},
                {"name": "Status", "value": run.status_display},
                {"name": "Triggered", "value": triggered},
                {"name": "Exit Code", "value": str(run.exit_code)},
                {"name": "Triggered by", "value": run.trigger_display},
            ],
            "text": f"**Error Log:**\n\n```\n{error_preview}\n```",
        }],
    }


def send_failure_notification(run) -> bool:
    """Sends a webhook notification for a failed Run. Never raises an exception."""
    setting = NotificationSetting.load()
    if not setting.webhook_url:
        logger.info("Notification skipped: no webhook URL configured.")
        return False

    is_timeout = run.status == "TIMEOUT"
    if is_timeout and not setting.notify_on_timeout:
        return False
    if not is_timeout and not setting.notify_on_failure:
        return False

    error_preview = _error_preview(run)
    if setting.provider == NotificationSetting.Provider.TEAMS:
        payload = _build_teams_payload(run, error_preview)
    else:
        payload = _build_slack_payload(run, error_preview)

    try:
        resp = requests.post(setting.webhook_url, json=payload, timeout=_WEBHOOK_TIMEOUT)
        resp.raise_for_status()
        logger.info("Notification sent: %s", run.job_name)
        return True
    except requests.RequestException as exc:
        logger.error("Notification failed (%s): %s", run.job_name, exc)
        return False
