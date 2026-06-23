"""URL configuration for the fundhub project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("reporting.urls")),
]
