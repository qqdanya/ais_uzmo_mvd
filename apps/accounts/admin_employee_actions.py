from django.contrib import messages
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from apps.audit.models import AuditLog

from .admin_employee_core import employee_display_name, employee_queryset
from .admin_employee_forms import EmployeeForm, employee_form_context
from .models import UserProfile


def kill_user_sessions(user):
    """Force out any session the user is already logged in with.

    is_active=False alone leaves an already-issued session cookie valid
    until it naturally expires - the auth backend only rejects inactive
    users on their *next* request, so without this a just-blocked user
    stays logged in for up to SESSION_COOKIE_AGE.
    """
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if str(session.get_decoded().get(SESSION_KEY)) == str(user.pk):
            session.delete()


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _sorted_names(items):
    return sorted((str(item) for item in items), key=str.casefold)


def employee_audit_values(user):
    profile = getattr(user, "profile", None)
    return {
        "username": user.username,
        "last_name": user.last_name,
        "first_name": user.first_name,
        "middle_name": getattr(profile, "middle_name", ""),
        "role": getattr(profile, "role", UserProfile.Role.OBSERVER),
        "allowed_departments": _sorted_names(profile.allowed_departments.all()) if profile else [],
        "writable_departments": _sorted_names(profile.writable_departments.all()) if profile else [],
        "allowed_organs": _sorted_names(profile.allowed_organs.all()) if profile else [],
        "writable_organs": _sorted_names(profile.writable_organs.all()) if profile else [],
        "is_active": user.is_active,
        "activation_status": "activated" if user.has_usable_password() else "needs_activation",
    }


def employee_form_audit_values(form, user):
    values = form.cleaned_data
    return {
        "username": user.username,
        "last_name": user.last_name,
        "first_name": user.first_name,
        "middle_name": values.get("middle_name", ""),
        "role": values.get("role") or UserProfile.Role.OBSERVER,
        "allowed_departments": _sorted_names(values.get("allowed_departments") or []),
        "writable_departments": _sorted_names(values.get("writable_departments") or []),
        "allowed_organs": _sorted_names(values.get("allowed_organs") or []),
        "writable_organs": _sorted_names(values.get("writable_organs") or []),
        "is_active": user.is_active,
        "activation_status": "activated" if user.has_usable_password() else "needs_activation",
    }


def changed_employee_values(old_values, new_values):
    keys = dict.fromkeys([*old_values, *new_values])
    changed = [key for key in keys if old_values.get(key) != new_values.get(key)]
    return (
        {key: old_values.get(key) for key in changed},
        {key: new_values.get(key) for key in changed},
    )


def write_employee_audit(request, user, action, summary, *, old_values=None, new_values=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        model_name="User",
        object_id=str(user.pk),
        object_repr=employee_display_name(user),
        old_values=old_values,
        new_values={"audit_event": summary, **(new_values or {})},
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def create_employee(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST, current_user=request.user)
        if form.is_valid():
            user = form.save()
            write_employee_audit(
                request,
                user,
                AuditLog.Action.CREATE,
                AuditLog.EventType.EMPLOYEE_CREATED,
                new_values=employee_form_audit_values(form, user),
            )
            messages.success(request, "Сотрудник создан. Передайте ему логин и код активации.")
            return redirect("admin_employee_detail", pk=user.pk)
    else:
        form = EmployeeForm(current_user=request.user)
    return employee_form_context(request, form=form, mode="create")


def edit_employee(request, pk):
    user = get_object_or_404(employee_queryset(), pk=pk)
    if request.method == "POST":
        old_values = employee_audit_values(user)
        form = EmployeeForm(request.POST, instance=user, current_user=request.user)
        if form.is_valid():
            user = form.save()
            old_changes, new_changes = changed_employee_values(
                old_values,
                employee_form_audit_values(form, user),
            )
            if new_changes:
                write_employee_audit(
                    request,
                    user,
                    AuditLog.Action.UPDATE,
                    AuditLog.EventType.EMPLOYEE_PERMISSIONS,
                    old_values=old_changes,
                    new_values=new_changes,
                )
            messages.success(request, "Права сотрудника обновлены.")
            return redirect("admin_employee_detail", pk=user.pk)
    else:
        form = EmployeeForm(instance=user, current_user=request.user)
    return employee_form_context(request, user=user, form=form, mode="edit")


def handle_employee_action(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk)
    action = request.POST.get("action")
    if user.pk == request.user.pk and action in {"block", "reset_activation", "delete"}:
        messages.error(request, "Нельзя выполнить это действие над собственной учётной записью.")
        return redirect("admin_employee_detail", pk=user.pk)
    if action == "delete":
        if not request.user.is_superuser:
            messages.error(request, "Окончательно удалить сотрудника может только руководитель.")
            return redirect("admin_employee_detail", pk=user.pk)
        display_name = employee_display_name(user)
        write_employee_audit(
            request,
            user,
            AuditLog.Action.DELETE,
            AuditLog.EventType.EMPLOYEE_DELETED,
            old_values=employee_audit_values(user),
        )
        user.delete()
        messages.success(request, f"Сотрудник {display_name} удалён.")
        return redirect("admin_employees_panel")
    profile, _ = UserProfile.objects.get_or_create(user=user)
    old_values = employee_audit_values(user)
    if action == "block":
        user.is_active = False
        user.save(update_fields=["is_active"])
        kill_user_sessions(user)
        old_changes, new_changes = changed_employee_values(old_values, employee_audit_values(user))
        if new_changes:
            write_employee_audit(
                request,
                user,
                AuditLog.Action.UPDATE,
                AuditLog.EventType.EMPLOYEE_BLOCKED,
                old_values=old_changes,
                new_values=new_changes,
            )
            messages.success(request, "Сотрудник заблокирован.")
        else:
            messages.info(request, "Сотрудник уже заблокирован.")
    elif action == "unblock":
        user.is_active = True
        user.save(update_fields=["is_active"])
        old_changes, new_changes = changed_employee_values(old_values, employee_audit_values(user))
        if new_changes:
            write_employee_audit(
                request,
                user,
                AuditLog.Action.UPDATE,
                AuditLog.EventType.EMPLOYEE_UNBLOCKED,
                old_values=old_changes,
                new_values=new_changes,
            )
            messages.success(request, "Сотрудник разблокирован.")
        else:
            messages.info(request, "Сотрудник уже разблокирован.")
    elif action == "reset_activation":
        user.set_unusable_password()
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        profile.activation_code = ""
        profile.ensure_activation_code()
        profile.save(update_fields=["activation_code"])
        new_values = employee_audit_values(user)
        new_values["activation_status"] = "new_activation_code"
        old_changes, new_changes = changed_employee_values(old_values, new_values)
        write_employee_audit(
            request,
            user,
            AuditLog.Action.UPDATE,
            AuditLog.EventType.EMPLOYEE_ACTIVATION_RESET,
            old_values=old_changes,
            new_values=new_changes,
        )
        messages.success(request, "Активация сброшена. Сотруднику нужно выдать новый код.")
    else:
        raise Http404
    return redirect("admin_employee_detail", pk=user.pk)
