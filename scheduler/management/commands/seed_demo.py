"""
Management command that creates sample (demo) Job records.

    python manage.py seed_demo

Creates Jobs that point to the sample scripts in the `scripts/` directory.
Since the scripts must be under SCRIPT_ALLOWED_ROOT, the command detects the
script root automatically and warns if it doesn't match.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from scheduler.models import Job

# (name, script_file, cron, timeout, active, description)
DEMO_JOBS = [
    ("Hello World", "hello.sh", "", 30, True,
     "The simplest example; try it with Run Now."),
    ("Nightly Backup", "backup.sh", "0 2 * * *", 3600, True,
     "Backup every night at 02:00."),
    ("Database Dump", "db_dump.sh", "0 */6 * * *", 1800, True,
     "Database backup every 6 hours."),
    ("Temp Cleanup", "cleanup_temp.sh", "30 3 * * 0", 600, True,
     "Temporary file cleanup every Sunday at 03:30."),
    ("Disk Check", "disk_check.sh", "*/15 * * * *", 60, True,
     "Disk usage check every 15 minutes (alerts if the threshold is exceeded)."),
    ("Service Health", "health_check.sh", "*/5 * * * *", 30, True,
     "HTTP health check every 5 minutes."),
    ("Random Fail (alert test)", "random_fail.sh", "", 30, True,
     "For testing the notification system; fails 50% of the time."),
    ("Long Running (timeout test)", "long_running.sh", "", 5, True,
     "For testing the timeout mechanism; killed after 5 seconds."),
]


class Command(BaseCommand):
    help = "Creates demo Job records pointing to the sample scripts under scripts/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Updates existing Jobs with the same name (default: skips them).",
        )

    def handle(self, *args, **options):
        allowed_root = Path(settings.SCRIPT_ALLOWED_ROOT).resolve()
        self.stdout.write(f"Script root (SCRIPT_ALLOWED_ROOT): {allowed_root}")

        if not allowed_root.is_dir():
            self.stderr.write(self.style.WARNING(
                f"WARNING: '{allowed_root}' not found. Copy the scripts there "
                f"or point SCRIPT_ALLOWED_ROOT in .env to the 'scripts/' directory."
            ))

        created, updated, skipped = 0, 0, 0
        for name, fname, cron, timeout, active, desc in DEMO_JOBS:
            script_path = str(allowed_root / fname)
            exists_on_disk = os.path.isfile(script_path)

            defaults = {
                "description": desc,
                "script_path": script_path,
                "working_directory": "",
                "cron_expression": cron,
                "timeout_seconds": timeout,
                "is_active": active,
            }

            job = Job.objects.filter(name=name).first()
            if job is None:
                Job.objects.create(name=name, **defaults)
                created += 1
                tag = "" if exists_on_disk else self.style.WARNING(" (script not on disk!)")
                self.stdout.write(self.style.SUCCESS(f"  + {name}") + tag)
            elif options["force"]:
                for k, v in defaults.items():
                    setattr(job, k, v)
                job.save()
                updated += 1
                self.stdout.write(f"  ~ {name} (updated)")
            else:
                skipped += 1
                self.stdout.write(f"  = {name} (already exists, skipped)")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {created} created, {updated} updated, {skipped} skipped."
        ))
        if created or updated:
            self.stdout.write("You can try them from the 'Scripts' page in the UI.")
