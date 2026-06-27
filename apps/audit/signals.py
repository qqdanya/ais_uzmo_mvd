from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import AuditLog
from .utils import client_ip


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    AuditLog.objects.create(user=user, action=AuditLog.Action.LOGIN, ip_address=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""))


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    AuditLog.objects.create(user=user, action=AuditLog.Action.LOGOUT, ip_address=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""))
