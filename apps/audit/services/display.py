import re
from pathlib import Path

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import capfirst

from apps.accounts.models import UserProfile
from apps.directory.models import Department, TerritorialOrganPhoto
from apps.requests_app.models import RequestStatusHistory
from apps.requests_app.permissions import can_preview_photo_asset

from apps.audit.models import AuditLog
from .constants import (
    ACTION_BADGES,
    ACTION_DISPLAY_LABELS,
    AUDIT_EVENT_SUMMARIES,
    EVENT_BADGES,
    MODEL_HIDDEN_FIELD_NAMES,
    MODEL_TABLES,
    SYSTEM_FIELD_NAMES,
)


AUDIT_FIELD_LABELS = {
    "username": "Логин",
    "middle_name": "Отчество",
    "role": "Роль в системе",
    "allowed_departments": "Доступные отделы",
    "allowed_organs": "Доступные территориальные органы",
    "is_active": "Вход разрешён",
    "is_staff": "Доступ к стандартной админ-панели",
    "is_superuser": "Полные права Django",
    "activation_status": "Состояние активации",
    "password_changed": "Пароль изменён",
    "django_groups": "Группы доступа Django",
    "django_permissions": "Дополнительные права Django",
    "request_stale_workdays": "Просроченные заявки, рабочих дней",
    "asset_stale_days": "Устаревшие сведения материальной базы, календарных дней",
}

LEGACY_EMPLOYEE_UPDATE_EVENTS = {
    AuditLog.EventType.EMPLOYEE_PERMISSIONS,
    AuditLog.EventType.EMPLOYEE_BLOCKED,
    AuditLog.EventType.EMPLOYEE_UNBLOCKED,
    AuditLog.EventType.EMPLOYEE_ACTIVATION_RESET,
    AuditLog.EventType.ACCOUNT_ACTIVATED,
}
AUDIT_PHOTO_PREVIEW_LIMIT = 24
TMC_ONE_SIDED_EVENTS = {
    AuditLog.EventType.TMC_ITEM_ADDED: "new",
    AuditLog.EventType.TMC_ITEM_REMOVED: "old",
}
EXPORT_GROUP_MODE_LABELS = {
    "requests": "По заявкам",
    "products": "По товарам",
    "organs": "По территориальным органам",
    "dates": "По датам",
}


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
        return f"{noun} перемещена в корзину" if noun == "Заявка" else f"{noun} перемещены в корзину"
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
    value = typographic_quotes(log.object_repr).strip()
    legacy_match = re.match(
        r"^(?:Создан(?:а|о)?|Добавлен(?:а|о)?|Измен[её]н(?:а|о)?|Удал[её]н(?:а|о)?)\s+"
        r"(?:запись|объект|изменение статуса заявки)\s*[«\"]?(.*?)[»\"]?$",
        value,
        flags=re.IGNORECASE,
    )
    return legacy_match.group(1).strip() if legacy_match else value


def field_label(model_name, field_name):
    if field_name in AUDIT_FIELD_LABELS:
        return AUDIT_FIELD_LABELS[field_name]
    if field_name == "photos":
        return "Прикрепленные фотографии"
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
    if value in (None, "", "None", "null"):
        return "Не указано"
    if field_name == "role":
        return str(dict(UserProfile.Role.choices).get(str(value), value))
    if field_name == "activation_status":
        return {
            "activated": "Активирована",
            "needs_activation": "Ожидает активации",
            "new_activation_code": "Ожидает активации по новому коду",
        }.get(str(value), str(value))
    if field_name == "allowed_departments" and isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Отделы не выбраны"
    if field_name == "allowed_organs" and isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Территориальные органы не выбраны"
    if field_name in {"django_groups", "django_permissions"} and isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Не назначены"
    model = model_class(model_name)
    field = None
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
                normalized_choices = {str(key): label for key, label in choices.items()}
                return str(normalized_choices.get(str(value), value))
        except Exception:
            field = None
    field_type = field.get_internal_type() if field else ""
    if field_type in {"BooleanField", "NullBooleanField"}:
        normalized = str(value).strip().lower()
        if normalized in {"true", "1"}:
            return "Да"
        if normalized in {"false", "0"}:
            return "Нет"
    if field_type == "DateField":
        date_value = parse_date(str(value)[:10])
        if date_value:
            return date_value.strftime("%d.%m.%Y")
    if field_type == "DateTimeField":
        datetime_value = parse_datetime(str(value))
        if datetime_value:
            if timezone.is_aware(datetime_value):
                datetime_value = timezone.localtime(datetime_value)
            return datetime_value.strftime("%d.%m.%Y %H:%M:%S")
    if field_type in {"FileField", "ImageField"}:
        return Path(str(value)).name
    if str(value) == "True":
        return "Да"
    if str(value) == "False":
        return "Нет"
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


def event_detail_value(key, value):
    if key == "format":
        return str(value).upper()
    if key == "group_mode":
        return EXPORT_GROUP_MODE_LABELS.get(str(value), value)
    return value


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
        if key == "username" and log.event_type in LEGACY_EMPLOYEE_UPDATE_EVENTS:
            if old_raw in (None, "", "None") and new_raw not in (None, "", "None"):
                continue
        if key == "username" and log.event_type == AuditLog.EventType.EMPLOYEE_DELETED:
            if old_raw in (None, "", "None") and new_raw not in (None, "", "None"):
                old_raw = new_raw
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
                "one_sided_value": TMC_ONE_SIDED_EVENTS.get(log.event_type) if key == "items" else "",
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
            return "Фотография перемещена в корзину"
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
            return "Папка фотографий перемещена в корзину"
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
        return "Запись перемещена в корзину"
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


def audit_photo_snapshot(log):
    old_values = log.old_values if isinstance(log.old_values, dict) else {}
    new_values = log.new_values if isinstance(log.new_values, dict) else {}
    if log.event_type == AuditLog.EventType.PHOTOS_ATTACHED:
        values = new_values
    elif log.event_type == AuditLog.EventType.PHOTOS_DETACHED:
        values = old_values
    else:
        values = next(
            (item for item in (new_values, old_values) if isinstance(item.get("photo_items"), list)),
            None,
        )

    if values is not None:
        raw_items = values.get("photo_items")
        if isinstance(raw_items, list):
            try:
                photo_count = max(int(values.get("photo_count", len(raw_items))), len(raw_items))
            except (TypeError, ValueError):
                photo_count = len(raw_items)
            return raw_items, True, photo_count
        if log.event_type in {AuditLog.EventType.PHOTOS_ATTACHED, AuditLog.EventType.PHOTOS_DETACHED}:
            names = [name.strip() for name in str(values.get("photos") or "").split(", ") if name.strip()]
            return [{"id": None, "name": name} for name in names], False, len(names)

    if log.model_name != "TerritorialOrganPhoto":
        return [], False, 0
    try:
        photo_id = int(log.object_id)
    except (TypeError, ValueError):
        return [], True, 0
    name = first_present_value(
        new_values.get("original_filename"),
        old_values.get("original_filename"),
        new_values.get("image"),
        old_values.get("image"),
    )
    return [{"id": photo_id, "name": Path(str(name)).name or "Фотография"}], True, 1


def audit_photo_previews(log, viewer):
    if not log.territorial_organ_id:
        return [], 0
    raw_items, has_structured_snapshot, photo_count = audit_photo_snapshot(log)
    snapshots = []
    if has_structured_snapshot:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                photo_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            snapshots.append({"id": photo_id, "name": str(item.get("name") or "Фотография")})
    else:
        snapshots = raw_items
    snapshots = snapshots[:AUDIT_PHOTO_PREVIEW_LIMIT]
    if not snapshots:
        return [], photo_count

    photos = TerritorialOrganPhoto.objects.select_related("folder", "created_by", "created_by__profile").filter(
        territorial_organ_id=log.territorial_organ_id
    )
    if has_structured_snapshot:
        photos_by_id = {photo.pk: photo for photo in photos.filter(pk__in=[item["id"] for item in snapshots])}
    else:
        photos_by_name = {}
        for photo in photos.filter(original_filename__in=[item["name"] for item in snapshots]):
            photos_by_name.setdefault(photo.original_filename, []).append(photo)
        if any(len(photos_by_name.get(item["name"], [])) != 1 for item in snapshots):
            return [], photo_count

    previews = []
    for item in snapshots:
        photo = photos_by_id.get(item["id"]) if has_structured_snapshot else photos_by_name[item["name"]][0]
        if photo and not can_preview_photo_asset(viewer, log.territorial_organ, photo):
            if not has_structured_snapshot:
                return [], photo_count
            photo = None
        previews.append({**item, "photo": photo})
    return previews, photo_count


def audit_photo_preview_title(log):
    if log.event_type == AuditLog.EventType.PHOTOS_ATTACHED:
        return "Прикрепленные фотографии"
    if log.event_type == AuditLog.EventType.PHOTOS_DETACHED:
        return "Открепленные фотографии"
    if log.event_type == AuditLog.EventType.PHOTO_RESTORED:
        return "Восстановленная фотография"
    if log.event_type == AuditLog.EventType.PHOTO_PURGED:
        return "Удалённая фотография"
    if log.event_type == AuditLog.EventType.FOLDER_RESTORED:
        return "Восстановленные фотографии"
    if log.event_type == AuditLog.EventType.FOLDER_PURGED:
        return "Удалённые фотографии"
    if log.event_type == AuditLog.EventType.PHOTO_DOWNLOADED:
        return "Скачанная фотография"
    if log.event_type == AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED:
        return "Фотографии в архиве"
    if log.model_name == "TerritorialOrganPhoto":
        if log.action == AuditLog.Action.CREATE:
            return "Созданная фотография"
        if log.action == AuditLog.Action.DELETE:
            return "Удалённая фотография"
        return "Фотография"
    return "Фотографии в папке"


def prepare_log(
    log,
    *,
    include_status_history=True,
    include_photo_previews=False,
    viewer=None,
    department_names=None,
    related_value_cache=None,
):
    log.action_badge = EVENT_BADGES.get(log.event_type, ACTION_BADGES.get(log.action, "audit-action-default"))
    log.action_display = ACTION_DISPLAY_LABELS.get(log.action, log.get_action_display())
    log.model_title = model_title(log.model_name)
    log.browser_summary = user_agent_summary(log.user_agent)
    log.change_rows = audit_changes(log, related_value_cache)
    log.summary = audit_summary(log, log.change_rows)
    log.inline_detail = ""
    if log.event_type == AuditLog.EventType.STATUS_CHANGED and log.change_rows:
        row = next((item for item in log.change_rows if item["field"] == "status"), log.change_rows[0])
        log.inline_detail = f"{row['old']} → {row['new']}"
    elif log.event_type in {AuditLog.EventType.PHOTOS_ATTACHED, AuditLog.EventType.PHOTOS_DETACHED} and log.change_rows:
        row = log.change_rows[0]
        log.inline_detail = row["new"] if log.event_type == AuditLog.EventType.PHOTOS_ATTACHED else row["old"]
    elif log.event_type == AuditLog.EventType.TABLE_EXPORTED:
        values = log.new_values or {}
        log.inline_detail = f"{str(values.get('format', '')).upper()} · {values.get('table_title', '')}".strip(" ·")
    values = log.new_values or {}
    detail_labels = {
        "format": "Формат",
        "table_title": "Таблица",
        "organ_count": "Территориальных органов",
        "group_mode": "Группировка",
        "photo_count": "Фотографий",
        "object_count": "Объектов",
        "request_photo_link_count": "Связей с заявками",
    }
    log.event_details = [
        (label, event_detail_value(key, values[key]))
        for key, label in detail_labels.items()
        if values.get(key) not in (None, "")
    ]
    log.detail_action_text = log.summary
    log.display_object_repr = audit_object_repr(log)
    log.is_object_action = bool(log.model_name) and log.action in {AuditLog.Action.CREATE, AuditLog.Action.UPDATE, AuditLog.Action.DELETE}
    log.show_territorial_organ = log.is_object_action and log.territorial_organ_id
    log.location_parts = audit_location(log, department_names)
    log.status_history = audit_status_history(log) if include_status_history else []
    photo_previews, photo_preview_count = (
        audit_photo_previews(log, viewer) if include_photo_previews and viewer else ([], 0)
    )
    log.photo_preview_extra_count = max(photo_preview_count - len(photo_previews), 0)
    log.photo_previews = photo_previews
    log.photo_previews_replace_changes = bool(log.photo_previews) and log.event_type in {
        AuditLog.EventType.PHOTOS_ATTACHED,
        AuditLog.EventType.PHOTOS_DETACHED,
    }
    log.photo_preview_title = audit_photo_preview_title(log) if log.photo_previews else ""
    return log


__all__ = [
    "prepare_log",
    "user_display_name",
]
