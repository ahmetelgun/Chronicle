# Example Scripts

This directory contains ready-to-use example Linux scripts for experimenting
with the Job Scheduler. They are all written with `set -euo pipefail` and produce
meaningful **exit codes** and logs, in a production style.

| Script | Purpose | Exit behavior |
|---|---|---|
| `hello.sh` | Simplest example; shows the injected `JOB_NAME`/`JOB_EXECUTION_ID` env vars | Always 0 (Success) |
| `backup.sh` | Archives a source directory as tar.gz, cleans up old backups | 0 / error=1 |
| `db_dump.sh` | PostgreSQL backup (simulates if pg_dump is missing) | 0 / error=1 |
| `cleanup_temp.sh` | Deletes temporary files older than N days | 0 / error=1 |
| `disk_check.sh` | Raises an **alert** if disk usage exceeds a threshold | 2 (Failed) if full |
| `health_check.sh` | HTTP service health check (curl) | 2xx/3xx=0, otherwise 2 |
| `random_fail.sh` | Fails 50% of the time to test the **notification system** | random 0/1 |
| `long_running.sh` | Runs long to test the **timeout** mechanism | SIGTERM→143 |

## Setup / usage

For security reasons the scheduler runs scripts only from under
`SCRIPT_ALLOWED_ROOT` (default `/opt/scripts`). Two options:

**A) Local development** — point the root at this directory in `.env` (relative to the project root):
```bash
# .env  (PROJECT_DIR = the absolute path where this repo lives)
SCRIPT_ALLOWED_ROOT=PROJECT_DIR/scripts
SCRIPT_PYTHONPATH=PROJECT_DIR/shared_lib
```

**B) Production** — copy the scripts to the standard location:
```bash
sudo mkdir -p /opt/scripts
sudo cp scripts/*.sh /opt/scripts/
sudo chmod +x /opt/scripts/*.sh
```

## Auto-loading demo jobs

Create example `Job` records pointing to these scripts with a single command:

```bash
python manage.py seed_demo
```

Then in the UI (Scripts page) you can see the jobs and try them with
**"Run Now"**, and watch the stdout/stderr output on the **Logs** page.

## Scenario experiments

- **Success:** `hello.sh` or `backup.sh` → status *Success*, exit 0.
- **Failure + notification:** `random_fail.sh` → *Failed* with 50% probability;
  if a webhook is configured, a Slack/Teams alert is sent. (On a server with a
  full disk, `disk_check.sh` also returns *Failed*.)
- **Timeout:** set the Job's *Timeout* value to 5 s for `long_running.sh` → the
  process is killed with SIGTERM, status *Timeout*, and a notification is triggered.

## ⚠️ About environment variables (env)

The env variables mentioned in the table above (`DISK_THRESHOLD`, `BACKUP_SOURCE`,
etc.) document the **default behavior** of the scripts. However, for security
reasons the Execution Engine runs scripts with a **sanitized environment** — that
is, env variables from the server shell are **not passed** to the child process
(only `PATH`, `HOME`, `LANG`, `JOB_NAME`, and `JOB_EXECUTION_ID` are injected).
For this reason, when running through the scheduler, the scripts use the
**default values** defined in the code.

To try a different value, either edit the default in the script (e.g.
`THRESHOLD=1` inside `disk_check.sh`), or add job-specific variables to the `env`
dictionary in `executor._run_subprocess`. (Per-job custom env support can easily
be extended by adding a `JSONField` to the model.)
