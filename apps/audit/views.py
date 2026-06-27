from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render

from .models import AuditLog


def is_admin(user):
    return user.is_superuser or getattr(getattr(user, "profile", None), "role", "") == "admin"


@login_required
@user_passes_test(is_admin)
def audit_log(request):
    logs = AuditLog.objects.select_related("user", "territorial_organ").all()
    if request.GET.get("user"):
        logs = logs.filter(user__username__icontains=request.GET["user"])
    if request.GET.get("action"):
        logs = logs.filter(action=request.GET["action"])
    if request.GET.get("organ"):
        logs = logs.filter(territorial_organ_id=request.GET["organ"])
    if request.GET.get("date_from"):
        logs = logs.filter(created_at__date__gte=request.GET["date_from"])
    if request.GET.get("date_to"):
        logs = logs.filter(created_at__date__lte=request.GET["date_to"])
    return render(request, "audit_log.html", {"logs": logs[:500], "actions": AuditLog.Action.choices})
