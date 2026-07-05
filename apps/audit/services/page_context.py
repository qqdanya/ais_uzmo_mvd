from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from apps.audit.models import AuditLog
from .constants import ACTION_DISPLAY_LABELS, OBJECT_FILTERS
from .display import prepare_log, user_display_name
from .filters import (
    audit_date_value,
    audit_filter_values,
    audit_has_filters,
    audit_multiselect_label,
    audit_pagination_fields,
    scoped_department_options,
    scoped_organ_queryset,
    scoped_user_queryset,
)


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
    organs = list(scoped_organ_queryset(request.user))
    department_filters = scoped_department_options(request.user)
    object_filters = [(key, label) for key, label, _ in OBJECT_FILTERS]
    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get("page"))
    for log in page.object_list:
        prepare_log(log)
    querystring = request.GET.copy()
    querystring.pop("page", None)
    querystring.pop("q", None)
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    selected_users = audit_filter_values(request, "user") if show_user_filter else []
    selected_actions = audit_filter_values(request, "action")
    selected_departments = audit_filter_values(request, "department") if show_department_filter else []
    selected_objects = audit_filter_values(request, "object")
    selected_organs = audit_filter_values(request, "organ")
    return {
        "title": title,
        "subtitle": subtitle,
        "page": page,
        "logs": page.object_list,
        "actions": actions,
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
        "selected_departments": selected_departments,
        "selected_objects": selected_objects,
        "selected_organs": selected_organs,
        "user_filter_label": audit_multiselect_label(
            selected_users,
            "Все пользователи",
            {account.username: user_display_name(account) for account in users},
        ),
        "action_filter_label": audit_multiselect_label(selected_actions, "Все действия", dict(actions)),
        "department_filter_label": audit_multiselect_label(selected_departments, "Все отделы", dict(department_filters)),
        "object_filter_label": audit_multiselect_label(selected_objects, "Все объекты", dict(object_filters)),
        "organ_filter_label": audit_multiselect_label(
            selected_organs,
            "Все территориальные органы",
            {str(organ.pk): organ.name for organ in organs},
        ),
        "has_filters": audit_has_filters(request, date_from, date_to, show_user_filter, show_department_filter),
        "reset_url": reverse(reset_url_name),
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
