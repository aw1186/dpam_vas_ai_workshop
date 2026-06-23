"""WSGI config for the fundhub project."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fundhub.settings")

application = get_wsgi_application()
