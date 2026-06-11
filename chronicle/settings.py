"""
Django settings — Web-Based Job Scheduler.

Configuration is read from environment variables following the 12-factor
principle (the .env file is loaded with python-dotenv).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load the .env file (if present)
load_dotenv(BASE_DIR / ".env")


def env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ==========================================================================
#  Core
# ==========================================================================
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 3rd party
    "django_apscheduler",
    # local
    "scheduler",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "chronicle.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "chronicle.wsgi.application"

# ==========================================================================
#  Database — SQLite
# ==========================================================================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Wait timeout to reduce SQLite concurrent-write lock contention.
        "OPTIONS": {"timeout": 20},
    }
}

# ==========================================================================
#  Password / Localization
# ==========================================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Europe/Istanbul")
USE_I18N = True
USE_TZ = True

# ==========================================================================
#  Static files
# ==========================================================================
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ==========================================================================
#  Auth — login/logout redirects
# ==========================================================================
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Django group names used for RBAC (mapped from LDAP groups).
ROLE_ADMIN = "Admin"
ROLE_OPERATOR = "Operator"
ROLE_VIEWER = "Viewer"

# LDAP group DNs used for RBAC. These constants and the mapping below are
# defined even when LDAP is disabled (signals.map_groups_to_roles uses them;
# kept outside the block so role mapping can also be exercised in local/test environments).
LDAP_GROUP_ADMIN = os.getenv(
    "LDAP_GROUP_ADMIN", "cn=sched_admin,ou=groups,dc=company,dc=local"
)
LDAP_GROUP_OPERATOR = os.getenv(
    "LDAP_GROUP_OPERATOR", "cn=sched_operator,ou=groups,dc=company,dc=local"
)
LDAP_GROUP_VIEWER = os.getenv(
    "LDAP_GROUP_VIEWER", "cn=sched_viewer,ou=groups,dc=company,dc=local"
)

# Mapping of LDAP group DN -> Django Group (role) name.
AUTH_LDAP_GROUP_MAPPING = {
    LDAP_GROUP_ADMIN: ROLE_ADMIN,
    LDAP_GROUP_OPERATOR: ROLE_OPERATOR,
    LDAP_GROUP_VIEWER: ROLE_VIEWER,
}

# ==========================================================================
#  Execution Engine settings
# ==========================================================================
# Scripts are only allowed to run from under this root directory.
SCRIPT_ALLOWED_ROOT = os.getenv("SCRIPT_ALLOWED_ROOT", "/opt/scripts")
SCHEDULER_MAX_WORKERS = int(os.getenv("SCHEDULER_MAX_WORKERS", "10"))

# Additional Python module paths injected into the subprocess so that scripts
# can import shared modules (e.g. a shared `parameters.py`). The running script's
# own directory is already added to sys.path by Python; this is for shared modules
# in other directories. Can be a directory list separated by os.pathsep (':') or commas.
# E.g.:  SCRIPT_PYTHONPATH=/opt/shared/lib:/opt/config
SCRIPT_PYTHONPATH = os.getenv("SCRIPT_PYTHONPATH", "")

# Logging: each execution writes a single .log file into the logs/ folder in the
# script's directory (the content is not written to the DB). .log files older than
# this age are automatically deleted.
LOG_DIRNAME = os.getenv("LOG_DIRNAME", "logs")
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
# RAM/CPU sampling interval (seconds). A smaller value gives more accurate peak RAM at slightly higher CPU cost.
RESOURCE_SAMPLE_INTERVAL = float(os.getenv("RESOURCE_SAMPLE_INTERVAL", "0.1"))

# ==========================================================================
#  LDAP Authentication & RBAC Mapping
#  (django-auth-ldap)
# ==========================================================================
AUTHENTICATION_BACKENDS = [
    # Local Django users first (superuser/fallback), then LDAP.
    "django.contrib.auth.backends.ModelBackend",
]

LDAP_ENABLED = env_bool("LDAP_ENABLED", True)

if LDAP_ENABLED:
    import ldap
    from django_auth_ldap.config import GroupOfNamesType, LDAPSearch

    # Add the LDAP backend to the chain.
    AUTHENTICATION_BACKENDS.insert(0, "django_auth_ldap.backend.LDAPBackend")

    AUTH_LDAP_SERVER_URI = os.getenv("LDAP_SERVER_URI", "ldap://localhost:389")

    # Bind with a service account and search for the user (more secure than an anonymous bind).
    AUTH_LDAP_BIND_DN = os.getenv("LDAP_BIND_DN", "")
    AUTH_LDAP_BIND_PASSWORD = os.getenv("LDAP_BIND_PASSWORD", "")

    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        os.getenv("LDAP_USER_SEARCH_BASE", "ou=people,dc=company,dc=local"),
        ldap.SCOPE_SUBTREE,
        "(uid=%(user)s)",  # for AD usually "(sAMAccountName=%(user)s)"
    )

    # Group search for group-based authorization.
    AUTH_LDAP_GROUP_SEARCH = LDAPSearch(
        os.getenv("LDAP_GROUP_SEARCH_BASE", "ou=groups,dc=company,dc=local"),
        ldap.SCOPE_SUBTREE,
        "(objectClass=groupOfNames)",  # for AD "(objectClass=group)"
    )
    AUTH_LDAP_GROUP_TYPE = GroupOfNamesType(name_attr="cn")

    # Map LDAP user attributes to Django User fields.
    AUTH_LDAP_USER_ATTR_MAP = {
        "first_name": "givenName",
        "last_name": "sn",
        "email": "mail",
    }

    # --------------------------------------------------------------
    #  RBAC: LDAP groups -> Django flags
    #  (LDAP_GROUP_* and AUTH_LDAP_GROUP_MAPPING are defined above, outside the block.)
    # --------------------------------------------------------------
    # Users in the Admin LDAP group become Django staff/superuser,
    # so they can access the admin panel and all administrative operations.
    AUTH_LDAP_USER_FLAGS_BY_GROUP = {
        "is_active": [LDAP_GROUP_ADMIN, LDAP_GROUP_OPERATOR, LDAP_GROUP_VIEWER],
        "is_staff": [LDAP_GROUP_ADMIN],
        "is_superuser": [LDAP_GROUP_ADMIN],
    }

    # Refresh group info from LDAP on every login (so privilege changes take effect immediately).
    AUTH_LDAP_ALWAYS_UPDATE_USER = True
    AUTH_LDAP_FIND_GROUP_PERMS = True
    AUTH_LDAP_CACHE_TIMEOUT = 300  # cache group memberships for 5 minutes

    # TLS / referral settings (referrals are usually disabled when working with AD).
    AUTH_LDAP_CONNECTION_OPTIONS = {
        ldap.OPT_REFERRALS: 0,
    }

# ==========================================================================
#  Logging
# ==========================================================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # Can be lowered to DEBUG level to debug LDAP issues.
        "django_auth_ldap": {"handlers": ["console"], "level": "WARNING"},
        "scheduler": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apscheduler": {"handlers": ["console"], "level": "WARNING"},
    },
}

# For HTTPS behind a reverse proxy (production):
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
