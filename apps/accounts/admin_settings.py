from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.audit.utils import write_audit

from .admin_thresholds import (
    THRESHOLD_HINTS,
    THRESHOLD_LABELS,
    THRESHOLD_LIMITS,
    default_thresholds,
    get_dashboard_thresholds,
    reset_dashboard_thresholds,
    save_dashboard_thresholds,
)


SETTING_FIELDS = (
    "request_stale_workdays",
    "asset_stale_days",
)


def threshold_rows(values=None, errors=None):
    values = values or get_dashboard_thresholds()
    errors = errors or {}
    defaults = default_thresholds()
    rows = []
    for key in SETTING_FIELDS:
        rows.append(
            {
                "key": key,
                "label": THRESHOLD_LABELS[key],
                "hint": THRESHOLD_HINTS[key],
                "value": values[key],
                "default": defaults[key],
                "min": THRESHOLD_LIMITS[key]["min"],
                "max": THRESHOLD_LIMITS[key]["max"],
                "error": errors.get(key, ""),
            }
        )
    return rows


def build_settings_context(values=None, errors=None):
    values = values or get_dashboard_thresholds()
    return {
        "active_tab": "settings",
        "threshold_rows": threshold_rows(values, errors),
        "settings_errors": errors or {},
        "back_url": reverse("admin_panel"),
    }


def handle_settings_post(request):
    old_values = get_dashboard_thresholds()
    if "reset" in request.POST:
        defaults = default_thresholds()
        if old_values == defaults:
            messages.info(request, "Пороговые значения уже установлены по умолчанию.")
            return None
        reset_dashboard_thresholds()
        write_audit(
            AuditLog.Action.UPDATE,
            user=request.user,
            old_values=old_values,
            new_values={"audit_event": AuditLog.EventType.SETTINGS_RESET, **defaults},
            request=request,
        )
        messages.success(request, "Пороговые значения возвращены к значениям по умолчанию.")
        return None

    values = {}
    errors = {}
    for key in SETTING_FIELDS:
        raw_value = (request.POST.get(key, "") or "").strip()
        limits = THRESHOLD_LIMITS[key]
        try:
            value = int(raw_value)
        except ValueError:
            errors[key] = "Укажите целое число."
            value = default_thresholds()[key]
        else:
            if value < limits["min"] or value > limits["max"]:
                errors[key] = f"Значение должно быть от {limits['min']} до {limits['max']}."
        values[key] = value

    if errors:
        messages.error(request, "Проверьте значения настроек.")
        return build_settings_context(values, errors)

    if values == old_values:
        messages.info(request, "Пороговые значения не изменились.")
        return None

    save_dashboard_thresholds(values)
    write_audit(
        AuditLog.Action.UPDATE,
        user=request.user,
        old_values=old_values,
        new_values={"audit_event": AuditLog.EventType.SETTINGS_UPDATED, **values},
        request=request,
    )
    messages.success(request, "Настройки административной панели сохранены.")
    return None
