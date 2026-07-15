from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import AuditLog
from .services.display import prepare_log
from .services.filters import filtered_logs, is_admin, scope_logs_for_user, user_can_view_log
from .services.page_context import render_audit_page


@login_required
@user_passes_test(is_admin)
def audit_log(request):
    logs = filtered_logs(request)
    return render_audit_page(
        request,
        logs,
        title="Журнал действий",
        subtitle="Администрирование",
        reset_url_name="audit_log",
        pagination_url_name="audit_log",
    )


@login_required
def my_audit_log(request):
    logs = filtered_logs(
        request,
        logs=scope_logs_for_user(AuditLog.objects.select_related("user", "user__profile", "territorial_organ").all(), request.user),
        show_user_filter=True,
        show_department_filter=True,
    )
    return render_audit_page(
        request,
        logs,
        title="Журнал действий",
        subtitle="Действия пользователей доступных отделов",
        reset_url_name="my_audit_log",
        pagination_url_name="my_audit_log",
        show_user_filter=True,
        show_department_filter=True,
        show_user_column=True,
    )


@login_required
def audit_detail(request, pk):
    log = get_object_or_404(AuditLog.objects.select_related("user", "user__profile", "territorial_organ"), pk=pk)
    if not user_can_view_log(request.user, log):
        raise Http404
    prepare_log(log, include_photo_previews=True, viewer=request.user)
    return render(request, "partials/audit_detail.html", {"log": log})


__all__ = [
    "audit_detail",
    "audit_log",
    "filtered_logs",
    "is_admin",
    "my_audit_log",
    "prepare_log",
    "scope_logs_for_user",
    "user_can_view_log",
]
