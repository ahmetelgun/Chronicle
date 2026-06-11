"""
View layer (FILE-BASED logging).

Execution logs live in files, not the DB; listing/dashboard use
services.logreader to scan script log directories (including standalone runs).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from scheduler.forms import JobForm, NotificationSettingForm
from scheduler.models import Job, NotificationSetting
from scheduler.permissions import (
    AdminRequiredMixin,
    ViewerRequiredMixin,
    can_manage,
    can_run,
    can_view,
)
from scheduler.services import executor, logreader

logger = logging.getLogger("scheduler")

_FAILURE_STATUSES = {"FAILED", "TIMEOUT", "ERROR", "ABORTED"}


class RolesContextMixin:
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_run"] = can_run(self.request.user)
        ctx["can_manage"] = can_manage(self.request.user)
        return ctx


# ---------------------------------------------------------------------------
#  Dashboard
# ---------------------------------------------------------------------------
class DashboardView(LoginRequiredMixin, ViewerRequiredMixin, RolesContextMixin, TemplateView):
    template_name = "scheduler/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        last_24h = now - timedelta(hours=24)

        jobs = Job.objects.all()
        runs = logreader.runs_since(last_24h)

        success = sum(1 for r in runs if r.status == "SUCCESS")
        failed = sum(1 for r in runs if r.status in _FAILURE_STATUSES)
        running = sum(1 for r in runs if r.is_running)
        total_done = success + failed
        success_rate = round((success / total_done) * 100, 1) if total_done else 0.0

        # Resource (RAM/CPU/duration) aggregations.
        durations = [r.duration_sec for r in runs if r.duration_sec is not None]
        cpus = [r.cpu_pct for r in runs if r.cpu_pct is not None]
        rams = [r.max_rss_mb for r in runs if r.max_rss_mb is not None]

        # Metric totals (merge the metric_summary entries).
        metric_totals = defaultdict(lambda: {"total": 0.0, "count": 0})
        for r in runs:
            for name, val in r.metric_summary.items():
                metric_totals[name]["total"] += val
                metric_totals[name]["count"] += 1
        metric_list = sorted(
            ({"name": k, "total": v["total"], "count": v["count"]}
             for k, v in metric_totals.items()),
            key=lambda x: x["total"], reverse=True,
        )

        # Event category totals.
        event_totals = defaultdict(int)
        for r in runs:
            for cat, cnt in r.event_summary.items():
                event_totals[cat] += int(cnt)
        event_list = sorted(
            ({"category": k, "count": v} for k, v in event_totals.items()),
            key=lambda x: x["count"], reverse=True,
        )

        # Custom footer fields (numeric ones only): total + average.
        footer_agg = defaultdict(lambda: {"sum": 0.0, "count": 0})
        for r in runs:
            for key, val in r.footer_extra.items():
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    continue
                footer_agg[key]["sum"] += num
                footer_agg[key]["count"] += 1
        custom_footer_list = sorted(
            ({"key": k,
              "total": round(d["sum"], 2),
              "avg": round(d["sum"] / d["count"], 2) if d["count"] else 0,
              "count": d["count"]}
             for k, d in footer_agg.items()),
            key=lambda x: x["key"],
        )

        ctx.update({
            "total_jobs": jobs.count(),
            "active_jobs": jobs.filter(is_active=True).count(),
            "inactive_jobs": jobs.filter(is_active=False).count(),
            "scheduled_jobs": jobs.filter(is_active=True).exclude(cron_expression="").count(),
            "success_24h": success,
            "failed_24h": failed,
            "running_now": running,
            "success_rate": success_rate,
            "recent_executions": runs[:10],
            "avg_duration": (sum(durations) / len(durations)) if durations else None,
            "avg_cpu_pct": round(sum(cpus) / len(cpus), 1) if cpus else None,
            "peak_rss_mb": max(rams) if rams else None,
            "avg_rss_mb": round(sum(rams) / len(rams), 1) if rams else None,
            "metric_totals": metric_list,
            "event_category_totals": event_list,
            "event_warning_24h": event_totals.get("warning", 0),
            "event_error_24h": event_totals.get("error", 0),
            "custom_footer_totals": custom_footer_list,
        })
        return ctx


# ---------------------------------------------------------------------------
#  Job list & detail
# ---------------------------------------------------------------------------
class JobListView(LoginRequiredMixin, ViewerRequiredMixin, RolesContextMixin, ListView):
    model = Job
    template_name = "scheduler/job_list.html"
    context_object_name = "jobs"
    paginate_by = 25

    def get_queryset(self):
        qs = Job.objects.all()
        search = self.request.GET.get("q", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(script_path__icontains=search))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class JobDetailView(LoginRequiredMixin, ViewerRequiredMixin, RolesContextMixin, DetailView):
    model = Job
    template_name = "scheduler/job_detail.html"
    context_object_name = "job"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["executions"] = logreader.list_runs_for_job(self.object)[:20]
        return ctx


# ---------------------------------------------------------------------------
#  Job management (Admin)
# ---------------------------------------------------------------------------
class JobCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Job
    form_class = JobForm
    template_name = "scheduler/job_form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f"'{form.instance.name}' script created.")
        response = super().form_valid(form)
        from scheduler.services import scheduler
        scheduler.sync_jobs()
        return response


class JobUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Job
    form_class = JobForm
    template_name = "scheduler/job_form.html"

    def form_valid(self, form):
        messages.success(self.request, f"'{form.instance.name}' script updated.")
        response = super().form_valid(form)
        from scheduler.services import scheduler
        scheduler.sync_jobs()
        return response


class JobDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = Job
    template_name = "scheduler/job_confirm_delete.html"
    success_url = reverse_lazy("job_list")

    def form_valid(self, form):
        name = self.object.name
        response = super().form_valid(form)
        from scheduler.services import scheduler
        scheduler.sync_jobs()
        messages.warning(self.request, f"'{name}' script deleted.")
        return response


@require_POST
def duplicate_job(request, pk: int):
    if not can_manage(request.user):
        messages.error(request, "You don't have permission for this action.")
        return redirect("job_list")
    source = get_object_or_404(Job, pk=pk)
    clone = source.duplicate(created_by=request.user, activate=False)
    messages.success(
        request,
        f"'{source.name}' duplicated → '{clone.name}'. "
        f"The copy was created inactive; review and activate it.",
    )
    return redirect("job_update", pk=clone.pk)


# ---------------------------------------------------------------------------
#  Run Now — manual asynchronous trigger (Admin/Operator)
# ---------------------------------------------------------------------------
@require_POST
def run_now(request, pk: int):
    if not can_run(request.user):
        messages.error(request, "You don't have permission for this action.")
        return redirect("job_list")

    job = get_object_or_404(Job, pk=pk)
    if not job.is_active:
        messages.warning(request, f"'{job.name}' is inactive and cannot run.")
        return redirect(request.META.get("HTTP_REFERER", reverse("job_list")))

    try:
        executor.run_job_async(job, trigger_type="MANUAL", user=request.user)
        messages.success(request, f"'{job.name}' started in the background. Logs will appear in a few seconds.")
    except executor.JobAlreadyRunningError:
        messages.warning(request, f"'{job.name}' is already running. Wait for it to finish.")
    except executor.ExecutionError as exc:
        messages.error(request, f"Execution error: {exc}")

    return redirect(request.META.get("HTTP_REFERER", reverse("job_list")))


@require_GET
def job_status_api(request):
    """Lightweight JSON status endpoint for live updates on the list page."""
    if not can_view(request.user):
        return JsonResponse({"detail": "forbidden"}, status=403)

    from scheduler.templatetags.scheduler_extras import status_class

    data = {}
    running_any = False
    for job in Job.objects.all():
        runs = logreader.list_runs_for_job(job)
        last = runs[0] if runs else None
        is_running = any(r.is_running for r in runs)
        running_any = running_any or is_running
        data[str(job.pk)] = {
            "is_running": is_running,
            "is_active": job.is_active,
            "status": last.status if last else "",
            "status_display": last.status_display if last else "—",
            "status_class": status_class(last.status) if last else "is-light",
            "started": (timezone.localtime(last.started).strftime("%d.%m %H:%M")
                        if last and last.started else ""),
        }
    return JsonResponse({"running_any": running_any, "jobs": data})


# ---------------------------------------------------------------------------
#  Logs (from files)
# ---------------------------------------------------------------------------
@require_GET
def log_list(request):
    if not can_view(request.user):
        raise Http404
    runs = logreader.list_all_runs()

    status = request.GET.get("status", "").strip()
    job_id = request.GET.get("job", "").strip()
    if status:
        runs = [r for r in runs if r.status == status]
    if job_id.isdigit():
        job = Job.objects.filter(pk=int(job_id)).first()
        if job:
            target = str(job.script_log_dir)
            runs = [r for r in runs if str(r.path.parent) == target]

    paginator = Paginator(runs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "scheduler/log_list.html", {
        "page_obj": page_obj,
        "runs": page_obj.object_list,
        "is_paginated": page_obj.has_other_pages(),
        "status_choices": [
            ("SUCCESS", "Success"), ("FAILED", "Failed"), ("TIMEOUT", "Timeout"),
            ("ERROR", "System Error"), ("RUNNING", "Running"), ("ABORTED", "Aborted"),
        ],
        "selected_status": status,
        "selected_job": job_id,
        "jobs": Job.objects.all().only("id", "name"),
        "can_run": can_run(request.user),
        "can_manage": can_manage(request.user),
    })


@require_GET
def log_detail(request, token: str):
    if not can_view(request.user):
        raise Http404
    run, lines = logreader.get_run_full(token)
    if run is None:
        raise Http404("Log not found.")
    return render(request, "scheduler/log_detail.html", {
        "run": run,
        "lines": lines,
        "can_run": can_run(request.user),
        "can_manage": can_manage(request.user),
    })


# ---------------------------------------------------------------------------
#  Settings — webhook (Admin)
# ---------------------------------------------------------------------------
class SettingsView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = NotificationSetting
    form_class = NotificationSettingForm
    template_name = "scheduler/settings.html"
    success_url = reverse_lazy("settings")

    def get_object(self, queryset=None):
        return NotificationSetting.load()

    def form_valid(self, form):
        messages.success(self.request, "Notification settings saved.")
        return super().form_valid(form)
