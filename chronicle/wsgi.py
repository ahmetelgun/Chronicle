"""WSGI entry point (gunicorn / uWSGI)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chronicle.settings")

application = get_wsgi_application()
