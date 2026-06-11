#!/usr/bin/env python3
"""
mail_report.py — Example script that writes its own log file.

With job_logger, the script writes its own execution log; this way, whether
triggered by the scheduler or run independently via manual/cron, it appears in
the dashboard. Each email's recipient + subject is logged under the 'email'
category; RAM/CPU/duration are automatic.

(shared_lib must be on SCRIPT_PYTHONPATH: for job_logger and parameters.)
"""
import random
import sys
import time

import job_logger

try:
    import parameters  # optional shared settings
    SUBJECT = f"Weekly Report ({parameters.ENVIRONMENT})"
except ImportError:
    SUBJECT = "Weekly Report"


def main() -> None:
    # Custom header fields: environment, campaign, version, etc.
    with job_logger.run(header={
        "env": getattr(parameters, "ENVIRONMENT", "dev") if parameters else "dev",
        "campaign": "weekly-report",
        "version": "2.3.1",
    }) as log:
        log.info("Processing mail report")
        recipients = [f"user{i}@company.local" for i in range(1, 21)]

        sent = warnings = errors = 0
        for addr in recipients:
            time.sleep(0.02)
            roll = random.random()
            if roll < 0.10:
                errors += 1
                log.error(f"Delivery failed: {addr}")
            elif roll < 0.25:
                warnings += 1
                log.warn(f"SMTP timeout, retried: {addr}")
                log.event("email", f"To: {addr} | subject: {SUBJECT} (retry)")
                sent += 1
            else:
                # Each successful email's recipient + subject is logged under the 'email' category.
                log.event("email", f"To: {addr} | subject: {SUBJECT}")
                sent += 1

        # Numeric metrics (aggregated in the dashboard).
        log.metric("emails_sent", sent)
        log.metric("emails_failed", errors)
        log.metric("smtp_warnings", warnings)

        # Custom footer fields: end-of-run summary information.
        log.footer("recipients_total", len(recipients))
        log.footer("delivery_rate_pct", round(sent / len(recipients) * 100, 1))

        log.info(f"Done: {sent} sent, {errors} errors")
        print(f"Finished. Sent: {sent}, Warnings: {warnings}, Errors: {errors}")

        # If there are too many errors, mark the run as 'Failed' (footer status=FAILED).
        if errors > 3:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
