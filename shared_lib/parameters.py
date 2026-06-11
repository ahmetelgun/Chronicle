"""
parameters.py — Shared configuration/constants module used by the scripts.

This file lives OUTSIDE the `scripts/` directory. Scripts access it via
`import parameters`. For this to work, this directory must be added to
SCRIPT_PYTHONPATH:

    SCRIPT_PYTHONPATH=/opt/chronicle/shared_lib
"""

# Example shared parameters
DB_HOST = "db.company.local"
DB_PORT = 5432
DB_NAME = "appdb"

BACKUP_ROOT = "/tmp/demo_backups"
RETENTION_DAYS = 7

API_BASE_URL = "https://api.company.local"
ENVIRONMENT = "production"


def connection_string() -> str:
    """Builds a connection string from the shared parameters (example helper)."""
    return f"postgresql://{DB_HOST}:{DB_PORT}/{DB_NAME}"
