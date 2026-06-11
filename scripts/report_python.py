#!/usr/bin/env python3
"""
report_python.py — Example that uses the shared parameters.py and writes its own log.
"""
import sys

import job_logger

try:
    import parameters
except ImportError:
    parameters = None


def main() -> None:
    with job_logger.run() as log:
        if parameters is None:
            log.error("Could not import the 'parameters' module (SCRIPT_PYTHONPATH?)")
            raise SystemExit(1)
        log.info("Generating report")
        log.out(f"Environment   : {parameters.ENVIRONMENT}")
        log.out(f"DB connection : {parameters.connection_string()}")
        log.metric("rows_exported", 1234)
        log.event("report", f"env={parameters.ENVIRONMENT} db={parameters.DB_NAME}")
        log.info("Report generated successfully")


if __name__ == "__main__":
    main()
