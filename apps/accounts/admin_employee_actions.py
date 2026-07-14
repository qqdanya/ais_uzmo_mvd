from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from apps.audit.models import AuditLog

from .admin_employee_core import employee_display_name, employee_queryset
from .admin_employee_forms import EmployeeForm, employee_form_context
from .models import UserProfile


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_employee_audit(request, user, action, summary, values=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        model_name="User",
        object_id=str(user.pk),
        object_repr=employee_display_name(user),
        new_values={"audit_event": summary, **(values or {})},
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def create_employee(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST, current_user=request.user)
        if form.is_valid():
            user = form.save()
            write_employee_audit(request, user, AuditLog.Action.CREATE, "employee_created", {"username": user.username})
            messages.success(request, "Сотрудник создан. Передайте ему логин и код активации.")
            return redirect("admin_employee_detail", pk=user.pk)
    else:
        form = EmployeeForm(current_user=request.user)
    return employee_form_context(request, form=form, mode="create")


def edit_employee(request, pk):
    user = get_object_or_404(employee_queryset(), pk=pk)
    if request.method == "POST":
        form = EmployeeForm(request.POST, instance=user, current_user=request.user)
        if form.is_valid():
            form.save()
            write_employee_audit(request, user, AuditLog.Action.UPDATE, "employee_permissions_updated", {"username": user.username})
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
        username = user.username
        display_name = employee_display_name(user)
        write_employee_audit(request, user, AuditLog.Action.DELETE, "employee_deleted", {"username": username})
        user.delete()
        messages.success(request, f"Сотрудник {display_name} удалён.")
        return redirect("admin_employees_panel")
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if action == "block":
        user.is_active = False
        user.save(update_fields=["is_active"])
        write_employee_audit(request, user, AuditLog.Action.UPDATE, "employee_blocked", {"username": user.username})
        messages.success(request, "Сотрудник заблокирован.")
    elif action == "unblock":
        user.is_active = True
        user.save(update_fields=["is_active"])
        write_employee_audit(request, user, AuditLog.Action.UPDATE, "employee_unblocked", {"username": user.username})
        messages.success(request, "Сотрудник разблокирован.")
    elif action == "reset_activation":
        user.set_unusable_password()
        user.is_active = True
        user.save(update_fields=["password", "is_active"])
        profile.activation_code = ""
        profile.ensure_activation_code()
        profile.save(update_fields=["activation_code"])
        write_employee_audit(request, user, AuditLog.Action.UPDATE, "employee_activation_reset", {"username": user.username})
        messages.success(request, "Активация сброшена. Сотруднику нужно выдать новый код.")
    else:
        raise Http404
    return redirect("admin_employee_detail", pk=user.pk)
