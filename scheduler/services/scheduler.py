"""
Scheduler service — cron-based triggering via django-apscheduler.

The BackgroundScheduler is started once (from apps.py) and periodically processes
the active jobs in the database according to their cron expressions. On each
trigger, the script is run through the executor.

Design note:
  * Since jobs are read dynamically from the database, instead of defining a
    separate APScheduler job for each job, we use a periodic "sync" job to
    synchronize the cron definitions in the DB with the APScheduler job store.
    This way, every change made through the web UI (add/edit/deactivate) is
    reflected within at most 1 minute.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger("scheduler")

# Module-level singleton scheduler instance.
_scheduler: BackgroundScheduler | None = None

# APScheduler job id prefix (combined with the DB job id).
_JOB_PREFIX = "scriptjob_"
# How long to keep old apscheduler execution records (days).
_HISTORY_RETENTION_DAYS = 7


def _parse_cron(expression: str) -> CronTrigger:
    """Converts a 'minute hour day month day-of-week' expression into a CronTrigger."""
    return CronTrigger.from_crontab(expression, timezone=settings.TIME_ZONE)


def _execute_scheduled_job(job_pk: int) -> None:
    """
    Callback invoked by APScheduler when the time is due.
    Reads the corresponding Job from the DB and runs it as a scheduler trigger.
    """
    # Local import: avoid importing models at module level before Django apps are loaded.
    from scheduler.models import Job
    from scheduler.services import executor

    try:
        job = Job.objects.get(pk=job_pk)
    except Job.DoesNotExist:
        logger.warning("Scheduled job not found (may have been deleted): pk=%s", job_pk)
        return

    if not job.is_active:
        logger.info("Inactive job skipped by the scheduler: %s", job.name)
        return

    try:
        executor.run_job_sync(
            job, trigger_type="SCHEDULER", user=None
        )
    except executor.JobAlreadyRunningError:
        # If the previous run has not finished yet, skip this trigger (overlap protection).
        logger.info("Scheduled job already running, skipped: %s", job.name)
    except executor.ExecutionError as exc:
        logger.error("Scheduled job could not be run (%s): %s", job.name, exc)


def sync_jobs() -> None:
    """
    Synchronizes the active/scheduled jobs in the DB with APScheduler.
    Called periodically (every minute) and after manual changes.
    """
    if _scheduler is None:
        return

    from scheduler.models import Job

    scheduled = {
        job.pk: job
        for job in Job.objects.filter(is_active=True).exclude(cron_expression="")
    }

    # Existing APScheduler jobs that carry our prefix.
    existing_ids = {
        j.id for j in _scheduler.get_jobs() if j.id.startswith(_JOB_PREFIX)
    }
    desired_ids = {f"{_JOB_PREFIX}{pk}" for pk in scheduled}

    # 1) Remove the ones that should no longer be scheduled.
    for stale in existing_ids - desired_ids:
        _scheduler.remove_job(stale)
        logger.info("Removed from schedule: %s", stale)

    # 2) Add new ones / update changed ones (replace_existing).
    for pk, job in scheduled.items():
        try:
            trigger = _parse_cron(job.cron_expression)
        except ValueError as exc:
            logger.error("Invalid cron expression (%s): %s — skipped", job.name, exc)
            continue
        _scheduler.add_job(
            _execute_scheduled_job,
            trigger=trigger,
            id=f"{_JOB_PREFIX}{pk}",
            args=[pk],
            name=job.name,
            replace_existing=True,
            max_instances=1,       # also prevent overlap at the APScheduler level
            misfire_grace_time=300,
            coalesce=True,
        )


def _cleanup_history() -> None:
    """Cleans up old APScheduler records and old .log files."""
    DjangoJobExecution.objects.delete_old_job_executions(
        _HISTORY_RETENTION_DAYS * 86400
    )
    # File-based log retention: delete .log files older than N days.
    try:
        from scheduler.services import logreader
        removed = logreader.cleanup_old_logs()
        if removed:
            logger.info("Retention: deleted %d old log file(s).", removed)
    except Exception:  # pragma: no cover
        logger.exception("Log retention cleanup failed")


def start() -> None:
    """
    Starts the scheduler. Called once from AppConfig.ready() in apps.py.
    Idempotent: does not start again if already running.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(
        timezone=settings.TIME_ZONE,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    # Jobs and history are stored in the Django DB (resilient to process restarts).
    _scheduler.add_jobstore(DjangoJobStore(), "default")

    # DB <-> scheduler synchronization: every minute.
    _scheduler.add_job(
        sync_jobs,
        trigger=CronTrigger(second="0"),  # at the start of every minute
        id="internal_sync_jobs",
        replace_existing=True,
        max_instances=1,
    )

    # History cleanup: every day at midnight.
    _scheduler.add_job(
        _cleanup_history,
        trigger=CronTrigger(hour="0", minute="0"),
        id="internal_cleanup_history",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.info("APScheduler started (timezone=%s).", settings.TIME_ZONE)

    # Synchronize once immediately at startup.
    sync_jobs()


def shutdown() -> None:
    """Shuts the scheduler down cleanly (for tests / shutdown)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped.")
