"""Application configuration — connects signals and starts the scheduler."""
import logging
import os
import sys

from django.apps import AppConfig

logger = logging.getLogger("scheduler")


class SchedulerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scheduler"
    verbose_name = "Job Scheduler"

    def ready(self):
        # Register the LDAP -> RBAC signals.
        from scheduler import signals  # noqa: F401

        # Start the scheduler only in normal server processes.
        # Do not start it for commands like migrate / makemigrations / test.
        if not self._should_start_scheduler():
            return

        try:
            from scheduler.services import scheduler
            scheduler.start()
        except Exception:  # pragma: no cover
            logger.exception("Failed to start the scheduler")

    @staticmethod
    def _should_start_scheduler() -> bool:
        # If a subcommand was invoked via manage.py (migrate, init_roles, shell, test...):
        #   * The scheduler is started only for 'runserver'.
        #   * It is not started for any other management command (avoids DB-during-init).
        is_manage = len(sys.argv) > 0 and sys.argv[0].endswith("manage.py")
        if is_manage:
            subcommand = sys.argv[1] if len(sys.argv) > 1 else ""
            if subcommand != "runserver":
                return False
            # runserver auto-reload: start only in the actual running process
            # (avoid double-starting in the reloader's main process).
            return os.environ.get("RUN_MAIN") == "true"

        # Non-manage.py (gunicorn/uWSGI -> wsgi.py): production server process, start it.
        return True
