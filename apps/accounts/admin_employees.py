from datetime import timedelta

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.views import prepare_log

from .admin_common import query_with
from .admin_employee_actions import create_employee, edit_employee, handle_employee_action
from .admin_employee_core import (
    ACTIVATION_OPTIONS,
    ACTIVITY_OPTIONS,
    VIEW_TABS,
    active_departments,
    active_filter_chips,
    activation_label,
    activation_state,
    activity_label,
    activity_state,
    created_requests_count,
    employee_activity_stats,
    employee_display_name,
    employee_filter_labels,
    employee_kpis,
    employee_presence_payload,
    employee_queryset,
    employee_row,
    employee_short_name,
    employee_status_counts,
    employee_view_tabs,
    filtered_users,
    format_departments_summary,
    format_organs_summary,
    has_all_departments_access,
    has_all_organs_access,
    last_seen_display,
    pagination_fields,
    profile_for,
    role_badge_class,
    role_label,
    selected_employee_filters,
    top_level_organs,
)
from .models import UserProfile


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_employees_context(request):
    users = employee_queryset()
    departments = list(active_departments())
    organs = list(top_level_organs())
    filters = selected_employee_filters(request, departments=departments, organs=organs)
    counts = employee_status_counts(users)
    filtered = filtered_users(request, users, departments=departments, organs=organs)
    paginator = Paginator(filtered, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    total_organs = len(organs)
    total_departments = len(departments)
    rows = [employee_row(user, total_organs, total_departments) for user in page.object_list]
    return {
        "active_tab": "employees",
        "employee_kpis": employee_kpis(counts),
        "activity_chart": employee_activity_stats(list(users), days=30),
        "presence_data_url": reverse("admin_employees_presence_data"),
        "view_tabs": employee_view_tabs(request, filters, counts),
        "filters": filters,
        "filter_labels": employee_filter_labels(filters, departments, organs),
        "employees": rows,
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_employees_panel"),
        "pagination_fields": pagination_fields(request),
        "role_options": UserProfile.Role.choices,
        "activity_options": ACTIVITY_OPTIONS.items(),
        "activation_options": ACTIVATION_OPTIONS.items(),
        "departments": departments,
        "organs": organs,
        "active_filter_chips": active_filter_chips(filters, departments, organs),
        "reset_url": reverse("admin_employees_panel"),
        "create_url": reverse("admin_employee_create"),
    }

def employee_detail_context(request, pk):
    user = get_object_or_404(employee_queryset(), pk=pk)
    profile = profile_for(user)
    total_organs = top_level_organs().count()
    total_departments = active_departments().count()
    logs = list(AuditLog.objects.select_related("user", "territorial_organ").filter(user=user).order_by("-created_at")[:12])
    for log in logs:
        prepare_log(log)
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    recent_actions = AuditLog.objects.filter(user=user, created_at__gte=thirty_days_ago).count()
    recent_created_requests = created_requests_count(user, since=thirty_days_ago)
    return {
        "active_tab": "employees",
        "employee": user,
        "profile": profile,
        "display_name": employee_display_name(user),
        "short_name": employee_short_name(user),
        "role_label": role_label(user),
        "role_class": role_badge_class(user),
        "activity_state": activity_state(profile),
        "activity_label": activity_label(profile),
        "last_seen": last_seen_display(profile),
        "activation_state": activation_state(user),
        "activation_label": activation_label(user),
        "organs_summary": format_organs_summary(profile, total_organs, user),
        "departments_summary": format_departments_summary(profile, total_departments, user),
        "allowed_organs": list(profile.allowed_organs.all()) if profile else [],
        "allowed_departments": list(profile.allowed_departments.all()) if profile else [],
        "all_organs": has_all_organs_access(user, profile),
        "all_departments": has_all_departments_access(user, profile, total_departments),
        "no_departments": not bool(profile and profile.allowed_departments.exists()),
        "no_organs": not bool(profile and profile.allowed_organs.exists()),
        "has_full_access": user.is_superuser,
        "recent_logs": logs,
        "recent_actions": recent_actions,
        "recent_created_requests": recent_created_requests,
        "edit_url": reverse("admin_employee_edit", kwargs={"pk": user.pk}),
        "back_url": reverse("admin_employees_panel"),
        "presence_data_url": reverse("admin_employees_presence_data"),
        "is_self": request.user.pk == user.pk,
    }
