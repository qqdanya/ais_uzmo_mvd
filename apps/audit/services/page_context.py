from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.directory.models import Department
from .constants import ACTION_DISPLAY_LABELS, OBJECT_FILTERS
from .display import prepare_log, user_display_name
from .filters import (
    audit_default_date_from,
    audit_default_date_to,
    audit_date_value,
    audit_filter_values,
    audit_has_filters,
    audit_multiselect_label,
    audit_pagination_fields,
    scoped_department_options,
    scoped_organ_queryset,
    scoped_user_queryset,
)


def _filter_url(request, base_url, *names):
    query = request.GET.copy()
    query.pop("page", None)
    for name in names:
        query.pop(name, None)
    encoded = query.urlencode()
    return f"{base_url}?{encoded}" if encoded else base_url


def _selection_chip(label, selected, labels, request, base_url, parameter):
    if not selected:
        return None
    value = labels.get(selected[0], selected[0]) if len(selected) == 1 else f"{label}: {len(selected)}"
    return {"label": f"{label}: {value}" if len(selected) == 1 else value, "url": _filter_url(request, base_url, parameter)}


def audit_context(
    request,
    logs,
    title,
    subtitle,
    reset_url_name,
    pagination_url_name,
    show_user_filter=True,
    show_department_filter=True,
    show_user_column=True,
):
    users = list(scoped_user_queryset(request.user))
    actions = [(value, ACTION_DISPLAY_LABELS.get(value, label)) for value, label in AuditLog.Action.choices]
    event_types = list(AuditLog.EventType.choices)
    organs = list(scoped_organ_queryset(request.user))
    department_filters = scoped_department_options(request.user)
    object_filters = [(key, label) for key, label, _ in OBJECT_FILTERS]
    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get("page"))
    department_names = {department.slug: department.name for department in Department.objects.filter(is_active=True)}
    related_value_cache = {}
    previous_operation_id = None
    for log in page.object_list:
        prepare_log(log, include_status_history=False, department_names=department_names, related_value_cache=related_value_cache)
        log.is_related_event = bool(log.operation_id and log.operation_id == previous_operation_id)
        previous_operation_id = log.operation_id or None
    querystring = request.GET.copy()
    querystring.pop("page", None)
    querystring.pop("q", None)
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    is_all_time = not date_from and not date_to
    all_time_params = querystring.copy()
    all_time_params["date_from"] = ""
    all_time_params["date_to"] = ""
    selected_users = audit_filter_values(request, "user") if show_user_filter else []
    selected_actions = audit_filter_values(request, "action")
    selected_event_types = audit_filter_values(request, "event_type")
    selected_departments = audit_filter_values(request, "department") if show_department_filter else []
    selected_objects = audit_filter_values(request, "object")
    selected_organs = audit_filter_values(request, "organ")
    base_url = reverse(reset_url_name)
    user_labels = {account.username: user_display_name(account) for account in users}
    action_labels = dict(actions)
    event_type_labels = dict(event_types)
    department_labels = dict(department_filters)
    object_labels = dict(object_filters)
    organ_labels = {str(organ.pk): organ.name for organ in organs}
    active_filter_chips = []
    chip_specs = [
        ("Пользователи", selected_users, user_labels, "user", show_user_filter),
        ("События", selected_event_types, event_type_labels, "event_type", True),
        ("Отделы", selected_departments, department_labels, "department", show_department_filter),
        ("Объекты", selected_objects, object_labels, "object", True),
        ("Органы", selected_organs, organ_labels, "organ", True),
    ]
    for label, selected, labels, parameter, visible in chip_specs:
        chip = _selection_chip(label, selected, labels, request, base_url, parameter) if visible else None
        if chip:
            active_filter_chips.append(chip)
    date_is_filter = (
        ("date_from" in request.GET and request.GET.get("date_from", "").strip() != audit_default_date_from())
        or ("date_to" in request.GET and request.GET.get("date_to", "").strip() != audit_default_date_to())
    )
    if date_is_filter:
        if not date_from and not date_to:
            period_label = "Период: за всё время"
        else:
            period_label = f"Период: {date_from or '…'} — {date_to or '…'}"
        active_filter_chips.append({"label": period_label, "url": _filter_url(request, base_url, "date_from", "date_to")})
    return {
        "title": title,
        "subtitle": subtitle,
        "page": page,
        "logs": page.object_list,
        "actions": actions,
        "event_types": event_types,
        "organs": organs,
        "department_filters": department_filters,
        "object_filters": object_filters,
        "users": users,
        "show_user_filter": show_user_filter,
        "show_department_filter": show_department_filter,
        "show_user_column": show_user_column,
        "date_from": date_from,
        "date_to": date_to,
        "selected_users": selected_users,
        "selected_actions": selected_actions,
        "selected_event_types": selected_event_types,
        "selected_departments": selected_departments,
        "selected_objects": selected_objects,
        "selected_organs": selected_organs,
        "user_filter_label": audit_multiselect_label(
            selected_users,
            "Все пользователи",
            user_labels,
        ),
        "action_filter_label": audit_multiselect_label(selected_actions, "Все действия", action_labels),
        "event_type_filter_label": audit_multiselect_label(selected_event_types, "Все события", event_type_labels),
        "department_filter_label": audit_multiselect_label(selected_departments, "Все отделы", department_labels),
        "object_filter_label": audit_multiselect_label(selected_objects, "Все объекты", object_labels),
        "organ_filter_label": audit_multiselect_label(
            selected_organs,
            "Все территориальные органы",
            organ_labels,
        ),
        "has_filters": audit_has_filters(request, date_from, date_to, show_user_filter, show_department_filter),
        "reset_url": reverse(reset_url_name),
        "active_filter_chips": active_filter_chips,
        "is_all_time": is_all_time,
        "all_time_url": f"{reverse(pagination_url_name)}?{all_time_params.urlencode()}",
        "querystring": querystring.urlencode(),
        "total_count": logs.count(),
        "page_links": paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "pagination_url": reverse(pagination_url_name),
        "pagination_fields": audit_pagination_fields(request, date_from, date_to, show_user_filter, show_department_filter),
    }


def render_audit_page(
    request,
    logs,
    title,
    subtitle,
    reset_url_name,
    pagination_url_name,
    show_user_filter=True,
    show_department_filter=True,
    show_user_column=True,
):
    return render(
        request,
        "audit_log.html",
        audit_context(
            request,
            logs,
            title,
            subtitle,
            reset_url_name,
            pagination_url_name,
            show_user_filter,
            show_department_filter,
            show_user_column,
        ),
    )


__all__ = ["audit_context", "render_audit_page"]
