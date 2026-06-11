"""Application URL routing."""
from django.urls import path

from scheduler import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Jobs
    path("jobs/", views.JobListView.as_view(), name="job_list"),
    path("jobs/new/", views.JobCreateView.as_view(), name="job_create"),
    path("jobs/<int:pk>/", views.JobDetailView.as_view(), name="job_detail"),
    path("jobs/<int:pk>/edit/", views.JobUpdateView.as_view(), name="job_update"),
    path("jobs/<int:pk>/delete/", views.JobDeleteView.as_view(), name="job_delete"),
    path("jobs/<int:pk>/run/", views.run_now, name="job_run"),
    path("jobs/<int:pk>/run-form/", views.job_run_form, name="job_run_form"),
    path("jobs/<int:pk>/duplicate/", views.duplicate_job, name="job_duplicate"),
    path("jobs/status/", views.job_status_api, name="job_status_api"),
    # Logs (from files; token = safe encoding of the file path)
    path("logs/", views.log_list, name="log_list"),
    path("logs/<str:token>/", views.log_detail, name="log_detail"),
    # Trends
    path("trends/", views.trends, name="trends"),
    # Settings
    path("settings/", views.SettingsView.as_view(), name="settings"),
]
