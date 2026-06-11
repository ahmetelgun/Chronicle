# Chronicle

> **Schedule, run, and log** enterprise Linux scripts (cron + chronicle).

A Django-based Job Scheduler for managing, scheduling, and manually triggering
dozens of Linux scripts on a server over the web; and for monitoring their
output, metrics, and resource usage.

The distinguishing aspect: **execution logs live in files, not in the database.**
Each script writes its own log file in a standard format; Chronicle scans and
displays these files. This way, **independent runs** executed outside the
scheduler (from cron or by hand) also appear on the dashboard.

- **Backend:** Django 5.2 (Python 3.13/3.14)
- **Frontend:** Django Templates + Bulma CSS
- **DB:** SQLite (jobs + settings only; logs in files)
- **Auth:** `django-auth-ldap` (LDAP/Active Directory)
- **RBAC:** LDAP groups → roles (Admin / Operator / Viewer)
- **Scheduler:** `django-apscheduler` (cron)
- **Resource measurement:** `psutil` (RAM/CPU, per execution)

## Features

- **Dashboard:** last 24-hour success/failure, run duration, **RAM/CPU**, custom
  metrics (`@metric`), event categories (`@event`), and the **custom footer
  fields** written by scripts — all collected from log files.
- **Job management:** add/edit/delete, **duplicate**, cron validation, timeout.
- **Run Now:** Admin/Operator trigger manually; asynchronous in the background, with **flock** locking.
- **Live list:** running jobs update without a page refresh once they finish (JSON polling).
- **Logs:** read from files; color-coded level stream, metric/event/custom-field summaries.
- **Notification:** Slack/Teams webhook alerts on failure/timeout.
- **Retention:** `.log` files older than N days are deleted automatically.

## Directory Structure

```
.
├── manage.py
├── requirements.txt / requirements-dev.txt
├── .env.example
├── chronicle/                  # project configuration (settings, urls, wsgi/asgi)
├── scheduler/                  # main application
│   ├── models.py               # Job, NotificationSetting  (logs in files!)
│   ├── views.py                # Dashboard, Jobs, Run Now, Logs (from files)
│   ├── forms.py / urls.py / admin.py / apps.py
│   ├── permissions.py          # RBAC mixins
│   ├── signals.py              # LDAP group → role mapping
│   ├── services/
│   │   ├── executor.py         # flock + subprocess + timeout
│   │   ├── logreader.py        # scan/parse log files (source of truth)
│   │   ├── scheduler.py        # APScheduler cron engine + retention
│   │   └── notifications.py    # Slack/Teams webhook
│   ├── management/commands/    # init_roles, seed_demo
│   ├── templatetags/ · tests/ · migrations/
├── shared_lib/
│   ├── job_logger.py           # SCRIPT-SIDE Python logging library
│   ├── job_logger.sh           # SCRIPT-SIDE bash logging helper
│   └── parameters.py           # example shared module (import parameters)
├── scripts/                    # example scripts (+ generated logs/)
├── examples/                   # example log files (format reference)
└── templates/                  # Bulma UI
```

## Setup

```bash
# 1) System dependency (for python-ldap)
#   Debian/Ubuntu: sudo apt-get install libldap2-dev libsasl2-dev libssl-dev
#   RHEL/CentOS  : sudo yum install openldap-devel
#   macOS        : brew install openldap

# 2) Virtual environment + packages
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # for testing: requirements-dev.txt

# 3) Environment variables
cp .env.example .env
#   In .env set SECRET_KEY, LDAP_*; to try without LDAP use LDAP_ENABLED=False
#   Set SCRIPT_ALLOWED_ROOT and SCRIPT_PYTHONPATH to your own paths

# 4) Database + roles + demo
python manage.py migrate
python manage.py init_roles               # Admin/Operator/Viewer
python manage.py seed_demo                # example jobs
python manage.py createsuperuser

# 5) Run
python manage.py runserver                # http://127.0.0.1:8000/
```

## Logging format (script-side)

Scripts write their own log files as `<script_directory>/logs/<name>-<UTC>-<pid>.log`.
In Python:

```python
import job_logger
with job_logger.run(header={"env": "production"}) as log:  # custom header
    log.info("started")
    log.event("email", f"To: {addr} | subject: {subj}")    # categorized event
    log.metric("emails_sent", 42)                          # numeric metric
    log.warn("smtp retry"); log.error("delivery failure")
    log.footer("delivery_rate_pct", 95.0)                  # custom footer
# on exit the footer (status, exit, duration, CPU/RAM, summaries) is written automatically
```

In Bash, `source shared_lib/job_logger.sh` → `jl_init`, `jl_info`, `jl_event`,
`jl_metric`, `jl_header`, `jl_footer`, `jl_close`.

For sample output, see the **`examples/`** directory.

| Directive | Log level | Result |
|---|---|---|
| `print()` / stdout | `OUT` | plain output |
| `log.info/warn/error` | `INFO`/`WARN`/`ERROR` | leveled line |
| `log.event(category, message)` | `EVENT` | counted by category (e.g. `email`) |
| `log.metric(name, value)` | `METRIC` | aggregated on the dashboard |
| `log.footer(name, number)` | footer field | average/total on the dashboard |

## Security

- Scripts run only from under `SCRIPT_ALLOWED_ROOT`; path traversal
  (`..`, symlinks) is blocked through validation.
- `subprocess` is called with `shell=False` (no command injection).
- On timeout the process is killed as a **process group** via SIGTERM→SIGKILL;
  meanwhile `job_logger` catches the SIGTERM and writes the footer as TIMEOUT.
- A second trigger while the same script is running is blocked with **flock**.
- Run Now requires POST + CSRF and Admin/Operator permission.
- Log files are referenced on the web by a **token** (not a path), and only those
  inside permitted log directories can be read.

## Production

- `DJANGO_DEBUG=False`, a real `SECRET_KEY`, `ALLOWED_HOSTS`.
- `gunicorn chronicle.wsgi:application` + nginx.
- **Important:** the scheduler runs in-process; use a single worker (`--workers 1`)
  or a separate scheduler process, otherwise jobs are triggered multiple times.
- For resource (RAM/CPU) measurement, `psutil` must be present in the scripts' interpreter.
- `python manage.py collectstatic`.

## Testing

```bash
pip install -r requirements-dev.txt
coverage run manage.py test scheduler && coverage report   # 105 tests, ~92%
```
