import re
from pathlib import Path

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import capfirst

from apps.directory.models import Department
from apps.requests_app.models import RequestStatusHistory

from apps.audit.models import AuditLog
from .constants import (
    ACTION_BADGES,
    ACTION_DISPLAY_LABELS,
    AUDIT_EVENT_SUMMARIES,
    MODEL_HIDDEN_FIELD_NAMES,
    MODEL_TABLES,
    SYSTEM_FIELD_NAMES,
)


def model_class(model_name):
    for model in apps.get_models():
        if model.__name__ == model_name:
            return model
    return None


def model_title(model_name):
    model = model_class(model_name)
    return capfirst(str(model._meta.verbose_name)) if model else (model_name or "Системное действие")


def user_display_name(user):
    if not user:
        return "Система"
    profile = getattr(user, "profile", None)
    if profile:
        return profile.display_name
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def table_action_noun(log):
    table = MODEL_TABLES.get(log.model_name)
    if not table:
        return "Запись"
    model = table["model"]
    verbose_name = str(model._meta.verbose_name)
    has_request_number = any(field.name == "request_number" for field in model._meta.fields)
    if has_request_number or "заявка" in verbose_name.lower():
        return "Заявка"
    return "Сведения"


def table_action_summary(log, changes):
    noun = table_action_noun(log)
    if log.action == AuditLog.Action.CREATE:
        return f"{noun} добавлена" if noun == "Заявка" else f"{noun} добавлены"
    if log.action == AuditLog.Action.DELETE:
        return f"{noun} удалена" if noun == "Заявка" else f"{noun} удалены"
    if changes:
        labels = ", ".join(row["label"] for row in changes[:3])
        if len(changes) > 3:
            labels = f"{labels} и другие поля"
        return f"{noun} отредактирована: {labels}" if noun == "Заявка" else f"{noun} отредактированы: {labels}"
    return ""


def typographic_quotes(value):
    return str(value or "").replace('"', "«", 1).replace('"', "»", 1)


def quoted_name(value):
    match = re.search(r"«([^»]+)»", typographic_quotes(value))
    return match.group(1) if match else ""


def first_present_value(*values):
    for value in values:
        if value not in (None, "", "None"):
            return value
    return ""


def audit_object_name(log, *field_names):
    object_name = quoted_name(log.object_repr)
    if object_name:
        return object_name
    old_values = log.old_values or {}
    new_values = log.new_values or {}
    for field_name in field_names:
        value = first_present_value(new_values.get(field_name), old_values.get(field_name))
        if value:
            return str(value)
    return typographic_quotes(log.object_repr)


def audit_object_repr(log):
    if log.model_name == "TerritorialOrganPhoto":
        image_name = audit_object_name(log, "original_filename", "image")
        return f"Фотография «{Path(image_name).name}»"
    if log.model_name == "TerritorialOrganPhotoFolder":
        return f"Папка фотографий «{audit_object_name(log, 'name')}»"
    if log.model_name == "TmcProduct":
        return f"Товар «{audit_object_name(log, 'name')}»"
    if log.model_name == "TmcRequestItem":
        return f"Позиция ТМЦ «{audit_object_name(log, 'name')}»"
    return typographic_quotes(log.object_repr)


def field_label(model_name, field_name):
    if field_name == "items":
        return "Сведения о потребности ТМЦ"
    model = model_class(model_name)
    if model:
        try:
            return capfirst(str(model._meta.get_field(field_name).verbose_name))
        except Exception:
            pass
    return capfirst(field_name.replace("_", " "))


def field_display_value(model_name, field_name, value, related_value_cache=None):
    if value in (None, "", "None"):
        return "Не указано"
    if value == "True":
        return "Да"
    if value == "False":
        return "Нет"
    model = model_class(model_name)
    if model:
        try:
            field = model._meta.get_field(field_name)
            if getattr(field, "remote_field", None) and field.remote_field.model:
                cache = related_value_cache if related_value_cache is not None else {}
                cache_key = (field.remote_field.model._meta.label_lower, str(value))
                if cache_key not in cache:
                    related = field.remote_field.model.objects.filter(pk=value).first()
                    cache[cache_key] = str(related) if related else str(value)
                return cache[cache_key]
            choices = dict(getattr(field, "choices", []) or [])
            if choices:
                return str(choices.get(value, value))
        except Exception:
            pass
    datetime_value = parse_datetime(str(value))
    if datetime_value:
        if timezone.is_aware(datetime_value):
            datetime_value = timezone.localtime(datetime_value)
        return datetime_value.strftime("%d.%m.%Y %H:%M:%S")
    date_value = parse_date(str(value))
    if date_value:
        return date_value.strftime("%d.%m.%Y")
    return str(value)


def user_agent_summary(value):
    value = value or ""
    if not value:
        return "Не указан"
    browser = "Браузер"
    if "Edg/" in value:
        browser = "Microsoft Edge"
    elif "Chrome/" in value and "Chromium" not in value:
        browser = "Google Chrome"
    elif "Firefox/" in value:
        browser = "Mozilla Firefox"
    elif "Safari/" in value and "Chrome/" not in value:
        browser = "Safari"

    os_name = "ОС не определена"
    if "Windows" in value:
        os_name = "Windows"
    elif "Android" in value:
        os_name = "Android"
    elif "iPhone" in value or "iPad" in value:
        os_name = "iOS"
    elif "Mac OS X" in value or "Macintosh" in value:
        os_name = "macOS"
    elif "Linux" in value:
        os_name = "Linux"
    return f"{browser} / {os_name}"


def relevant_keys(log):
    old_values = log.old_values or {}
    new_values = log.new_values or {}
    keys = list(dict.fromkeys([*old_values.keys(), *new_values.keys()]))
    hidden_fields = SYSTEM_FIELD_NAMES | MODEL_HIDDEN_FIELD_NAMES.get(log.model_name, set())
    return [key for key in keys if key not in hidden_fields]


def audit_changes(log, related_value_cache=None):
    old_values = log.old_values or {}
    new_values = log.new_values or {}
    rows = []
    for key in relevant_keys(log):
        old_raw = old_values.get(key)
        new_raw = new_values.get(key)
        if log.action == AuditLog.Action.UPDATE and str(old_raw) == str(new_raw):
            continue
        if log.action == AuditLog.Action.CREATE and new_raw in (None, "", "None"):
            continue
        rows.append(
            {
                "field": key,
                "label": field_label(log.model_name, key),
                "old": field_display_value(log.model_name, key, old_raw, related_value_cache),
                "new": field_display_value(log.model_name, key, new_raw, related_value_cache),
            }
        )
    return rows


def audit_summary(log, changes=None):
    if log.action == AuditLog.Action.LOGIN:
        return "Вход в систему"
    if log.action == AuditLog.Action.LOGOUT:
        return "Выход из системы"
    audit_event = (log.new_values or {}).get("audit_event")
    if audit_event in AUDIT_EVENT_SUMMARIES:
        return AUDIT_EVENT_SUMMARIES[audit_event]
    changes = audit_changes(log) if changes is None else changes
    changed_fields = {row["field"]: row for row in changes}
    if log.model_name == "TerritorialOrganPhoto":
        if log.action == AuditLog.Action.CREATE:
            return "Фотография добавлена"
        if log.action == AuditLog.Action.DELETE:
            return "Фотография удалена"
        if set(changed_fields) == {"description"}:
            old_description = changed_fields["description"]["old"]
            new_description = changed_fields["description"]["new"]
            if old_description == "Не указано" and new_description != "Не указано":
                return "Добавлено описание фотографии"
            if old_description != "Не указано" and new_description == "Не указано":
                return "Удалено описание фотографии"
            return "Изменено описание фотографии"
        if "image" in changed_fields:
            return "Заменено изображение фотографии"
        if "folder" in changed_fields:
            return "Фотография перемещена в папку"
        if changes:
            return "Фотография отредактирована"
    if log.model_name == "TerritorialOrganPhotoFolder":
        if log.action == AuditLog.Action.CREATE:
            return "Папка фотографий создана"
        if log.action == AuditLog.Action.DELETE:
            return "Папка фотографий удалена"
        if "name" in changed_fields:
            return "Папка фотографий переименована"
        if "parent" in changed_fields:
            return "Папка фотографий перемещена"
        if changes:
            return "Папка фотографий отредактирована"
    if log.model_name in MODEL_TABLES:
        summary = table_action_summary(log, changes)
        if summary:
            return summary
    if log.action == AuditLog.Action.CREATE:
        return "Запись добавлена"
    if log.action == AuditLog.Action.DELETE:
        return "Запись удалена"
    if changes:
        labels = ", ".join(row["label"] for row in changes[:3])
        if len(changes) > 3:
            labels = f"{labels} и другие поля"
        return f"Запись отредактирована: {labels}"
    return typographic_quotes(log.object_repr) or log.get_action_display()


def audit_location(log, department_names=None):
    if log.action not in {AuditLog.Action.CREATE, AuditLog.Action.UPDATE, AuditLog.Action.DELETE}:
        return []
    parts = []
    if log.territorial_organ_id:
        parts.append(("Территориальный орган", str(log.territorial_organ)))
    table = MODEL_TABLES.get(log.model_name)
    if table:
        if department_names is not None:
            department_name = department_names.get(table["department"])
            if department_name:
                parts.append(("Отдел", department_name))
            table_title = table.get("parent_title") or table["title"]
            parts.append(("Раздел", table_title))
            return parts
        department = Department.objects.filter(slug=table["department"], is_active=True).first()
        if department:
            parts.append(("Отдел", department.name))
        table_title = table.get("parent_title") or table["title"]
        parts.append(("Раздел", table_title))
    return parts


def audit_status_history(log):
    if log.model_name not in MODEL_TABLES or not log.object_id:
        return []
    model = model_class(log.model_name)
    if not model:
        return []
    try:
        object_id = int(log.object_id)
    except (TypeError, ValueError):
        return []
    content_type = ContentType.objects.get_for_model(model)
    return list(
        RequestStatusHistory.objects.select_related("changed_by")
        .filter(content_type=content_type, object_id=object_id)
        .order_by("-changed_at", "-id")
    )


def prepare_log(log, *, include_status_history=True, department_names=None, related_value_cache=None):
    log.action_badge = ACTION_BADGES.get(log.action, "audit-action-default")
    log.action_display = ACTION_DISPLAY_LABELS.get(log.action, log.get_action_display())
    log.model_title = model_title(log.model_name)
    log.browser_summary = user_agent_summary(log.user_agent)
    log.change_rows = audit_changes(log, related_value_cache)
    log.summary = audit_summary(log, log.change_rows)
    log.detail_action_text = log.summary
    log.display_object_repr = audit_object_repr(log)
    log.is_object_action = log.action in {AuditLog.Action.CREATE, AuditLog.Action.UPDATE, AuditLog.Action.DELETE}
    log.show_territorial_organ = log.is_object_action and log.territorial_organ_id
    log.location_parts = audit_location(log, department_names)
    log.status_history = audit_status_history(log) if include_status_history else []
    return log


__all__ = [
    "prepare_log",
    "user_display_name",
]
