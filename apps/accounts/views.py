from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.audit.views import prepare_log
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import NeedStatus, TmcProduct
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_assets import build_asset_category_detail_context, build_asset_organ_detail_context, build_asset_organ_summary_context, build_assets_context
from .admin_departments import build_department_detail_context, build_departments_context
from .admin_employees import build_employees_context, create_employee, edit_employee, employee_detail_context, employee_presence_payload, handle_employee_action
from .admin_organs import build_organ_detail_context, build_organs_context
from .admin_requests import build_request_detail_context, build_requests_context
from .admin_settings import build_settings_context, handle_settings_post
from .admin_summary import SUMMARY_DATA_CACHE_SECONDS, build_summary_context, build_summary_payload, summary_data_cache_key
from .admin_trash import (
    add_action_message,
    build_trash_context,
    permanently_delete_folder_tree,
    permanently_delete_photo,
    restore_folder_tree,
    restore_photo,
    restore_request_record,
)
from .forms import AccountActivationForm
from .models import UserProfile


def activate_account(request):
    form = AccountActivationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Учетная запись активирована. Теперь можно войти в систему.")
        return redirect("login")
    return render(request, "registration/activate_account.html", {"form": form})


def admin_access_allowed(user):
    profile = getattr(user, "profile", None)
    return user.is_superuser or getattr(profile, "role", "") == UserProfile.Role.ADMIN


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not admin_access_allowed(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def active_request_models():
    seen = set()
    for table in TABLE_BY_KEY.values():
        model = table["model"]
        if model in seen:
            continue
        seen.add(model)
        yield model


def active_requests_count(status):
    total = 0
    for model in active_request_models():
        field_names = {field.name for field in model._meta.fields}
        if {"status", "is_deleted"}.issubset(field_names):
            total += model.objects.filter(is_deleted=False, status=status).count()
    return total


def employee_rows(users):
    rows = []
    for user in users:
        profile = getattr(user, "profile", None)
        departments = list(profile.allowed_departments.all()) if profile else []
        organs = list(profile.allowed_organs.all()) if profile else []
        rows.append(
            {
                "user": user,
                "profile": profile,
                "display_name": profile.display_name if profile else user.get_full_name() or user.username,
                "role": profile.get_role_display() if profile else "Без профиля",
                "is_online": bool(profile and profile.is_online),
                "needs_activation": bool(profile and profile.needs_activation),
                "departments": departments[:2],
                "departments_extra": max(len(departments) - 2, 0),
                "organs": organs[:2],
                "organs_extra": max(len(organs) - 2, 0),
            }
        )
    return rows


def department_access_rows(profiles):
    profile_list = list(profiles)
    rows = []
    for department in Department.objects.filter(is_active=True).order_by("order_number", "name"):
        rows.append(
            {
                "department": department,
                "employee_count": sum(1 for profile in profile_list if department in profile.allowed_departments.all()),
            }
        )
    return rows


@login_required
@require_POST
def presence_ping(request):
    profile = getattr(request.user, "profile", None)
    if profile:
        profile.last_seen_at = timezone.now()
        profile.save(update_fields=["last_seen_at"])
    return HttpResponse(status=204)


@admin_required
def admin_panel(request):

    User = get_user_model()
    users = (
        User.objects.filter(is_active=True)
        .select_related("profile")
        .prefetch_related("profile__allowed_departments", "profile__allowed_organs")
        .order_by("last_name", "first_name", "username")
    )
    profiles = [user.profile for user in users if hasattr(user, "profile")]
    awaiting_activation = [profile for profile in profiles if profile.needs_activation]
    online_profiles = [profile for profile in profiles if profile.is_online]
    today = timezone.localdate()
    recent_logs = list(AuditLog.objects.select_related("user", "territorial_organ").order_by("-created_at")[:7])
    for log in recent_logs:
        prepare_log(log)

    context = {
        "metrics": [
            {"label": "Сотрудников", "value": users.count(), "icon": "bi-people"},
            {"label": "Онлайн сейчас", "value": len(online_profiles), "icon": "bi-broadcast"},
            {"label": "Ожидают активации", "value": len(awaiting_activation), "icon": "bi-person-check"},
            {"label": "Территориальных органов", "value": TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).count(), "icon": "bi-building"},
            {"label": "Заявок в работе", "value": active_requests_count(NeedStatus.IN_WORK), "icon": "bi-clipboard-check"},
            {"label": "Событий сегодня", "value": AuditLog.objects.filter(created_at__date=today).count(), "icon": "bi-activity"},
        ],
        "employees": employee_rows(list(users[:12])),
        "awaiting_activation": awaiting_activation[:6],
        "online_profiles": online_profiles[:6],
        "department_access": department_access_rows(profiles),
        "recent_logs": recent_logs,
        "data_summary": [
            {"label": "Активных отделов", "value": Department.objects.filter(is_active=True).count(), "icon": "bi-diagram-3"},
            {"label": "Справочник ТМЦ", "value": TmcProduct.objects.filter(is_active=True).count(), "icon": "bi-box-seam"},
            {"label": "Фотографий", "value": TerritorialOrganPhoto.objects.filter(is_deleted=False).count(), "icon": "bi-images"},
            {"label": "Папок фотографий", "value": TerritorialOrganPhotoFolder.objects.filter(is_deleted=False).count(), "icon": "bi-folder2-open"},
        ],
    }
    context.update(build_summary_context(request))
    template_name = "admin_panel/_panel.html" if request.headers.get("HX-Request") else "admin_panel/index.html"
    return render(request, template_name, context)


@admin_required
def admin_requests_panel(request):
    return render(request, "admin_panel/requests.html", build_requests_context(request))


@admin_required
def admin_request_detail(request, table_key, pk):
    return render(request, "admin_panel/request_detail.html", build_request_detail_context(request, table_key, pk))


@admin_required
def admin_organs_panel(request):
    return render(request, "admin_panel/organs.html", build_organs_context(request))


@admin_required
def admin_organ_detail(request, pk):
    return render(request, "admin_panel/organ_detail.html", build_organ_detail_context(request, pk))


@admin_required
def admin_departments_panel(request):
    return render(request, "admin_panel/departments.html", build_departments_context(request))


@admin_required
def admin_department_detail(request, department_slug):
    return render(request, "admin_panel/department_detail.html", build_department_detail_context(request, department_slug))


@admin_required
def admin_assets_panel(request):
    return render(request, "admin_panel/assets.html", build_assets_context(request))


@admin_required
def admin_asset_category_detail(request, category_key):
    return render(request, "admin_panel/asset_category_detail.html", build_asset_category_detail_context(request, category_key))


@admin_required
def admin_asset_organ_summary(request, organ_id):
    return render(request, "admin_panel/asset_organ_summary.html", build_asset_organ_summary_context(request, organ_id))


@admin_required
def admin_asset_organ_detail(request, category_key, organ_id):
    return render(request, "admin_panel/asset_organ_detail.html", build_asset_organ_detail_context(request, category_key, organ_id))


@admin_required
def admin_employees_panel(request):
    return render(request, "admin_panel/employees.html", build_employees_context(request))


@admin_required
def admin_employee_detail(request, pk):
    return render(request, "admin_panel/employee_detail.html", employee_detail_context(request, pk))


@admin_required
def admin_employee_create(request):
    result = create_employee(request)
    if hasattr(result, "status_code"):
        return result
    return render(request, "admin_panel/employee_form.html", result)


@admin_required
def admin_employee_edit(request, pk):
    result = edit_employee(request, pk)
    if hasattr(result, "status_code"):
        return result
    return render(request, "admin_panel/employee_form.html", result)


@admin_required
@require_POST
def admin_employee_action(request, pk):
    return handle_employee_action(request, pk)


@admin_required
def admin_employees_presence_data(request):
    return JsonResponse(employee_presence_payload())


@admin_required
def admin_threshold_settings(request):
    context = None
    if request.method == "POST":
        context = handle_settings_post(request)
        if context is None:
            return redirect("admin_threshold_settings")
    return render(request, "admin_panel/settings.html", context or build_settings_context())



@admin_required
def admin_trash_panel(request):
    return render(request, "admin_panel/trash.html", build_trash_context(request))


@admin_required
@require_POST
def admin_trash_restore_request(request, table_key, pk):
    add_action_message(request, restore_request_record(request, table_key, pk))
    return redirect("admin_trash_panel")


@admin_required
@require_POST
def admin_trash_restore_photo(request, pk):
    add_action_message(request, restore_photo(request, pk))
    return redirect("admin_trash_panel")


@admin_required
@require_POST
def admin_trash_purge_photo(request, pk):
    add_action_message(request, permanently_delete_photo(request, pk))
    return redirect("admin_trash_panel")


@admin_required
@require_POST
def admin_trash_restore_folder(request, pk):
    add_action_message(request, restore_folder_tree(request, pk))
    return redirect("admin_trash_panel")


@admin_required
@require_POST
def admin_trash_purge_folder(request, pk):
    add_action_message(request, permanently_delete_folder_tree(request, pk))
    return redirect("admin_trash_panel")


@admin_required
def admin_summary_data(request):
    metric = request.GET.get("org_metric", "in_work")
    cache_key = summary_data_cache_key(request, metric)
    payload = cache.get(cache_key)
    if payload is None:
        payload = build_summary_payload(request, metric=metric)
        cache.set(cache_key, payload, SUMMARY_DATA_CACHE_SECONDS)
    return JsonResponse(payload)
