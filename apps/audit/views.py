from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Min, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import RequestStatusHistory
from apps.requests_app.registry import TABLE_BY_KEY

from .models import AuditLog


SYSTEM_FIELD_NAMES = {"id", "created_at", "updated_at", "created_by", "updated_by", "is_deleted"}
ACTION_DISPLAY_LABELS = {
    AuditLog.Action.CREATE: "Создание",
    AuditLog.Action.UPDATE: "Редактирование",
    AuditLog.Action.DELETE: "Удаление",
    AuditLog.Action.LOGIN: "Вход",
    AuditLog.Action.LOGOUT: "Выход",
}
ACTION_BADGES = {
    AuditLog.Action.CREATE: "audit-action-create",
    AuditLog.Action.UPDATE: "audit-action-update",
    AuditLog.Action.DELETE: "audit-action-delete",
    AuditLog.Action.LOGIN: "audit-action-login",
    AuditLog.Action.LOGOUT: "audit-action-logout",
}
MODEL_TABLES = {config["model"].__name__: config for config in TABLE_BY_KEY.values()}


def is_admin(user):
    return user.is_superuser or getattr(getattr(user, "profile", None), "role", "") == "admin"


def model_class(model_name):
    for model in apps.get_models():
        if model.__name__ == model_name:
            return model
    return None


def model_title(model_name):
    model = model_class(model_name)
    return str(model._meta.verbose_name).capitalize() if model else (model_name or "Системное действие")


def typographic_quotes(value):
    return str(value or "").replace('"', "«", 1).replace('"', "»", 1)


def field_label(model_name, field_name):
    if field_name == "items":
        return "Сведения о потребности ТМЦ"
    model = model_class(model_name)
    if model:
        try:
            return str(model._meta.get_field(field_name).verbose_name).capitalize()
        except Exception:
            pass
    return field_name.replace("_", " ").capitalize()


def field_display_value(model_name, field_name, value):
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
                related = field.remote_field.model.objects.filter(pk=value).first()
                return str(related) if related else str(value)
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
    return [key for key in keys if key not in SYSTEM_FIELD_NAMES]


def audit_changes(log):
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
                "old": field_display_value(log.model_name, key, old_raw),
                "new": field_display_value(log.model_name, key, new_raw),
            }
        )
    return rows


def audit_summary(log):
    if log.action == AuditLog.Action.LOGIN:
        return "Вход в систему"
    if log.action == AuditLog.Action.LOGOUT:
        return "Выход из системы"
    changes = audit_changes(log)
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
            return "Папка с фотографиями создана"
        if log.action == AuditLog.Action.DELETE:
            return "Папка с фотографиями удалена"
        if "name" in changed_fields:
            return "Папка с фотографиями переименована"
        if "parent" in changed_fields:
            return "Папка с фотографиями перемещена"
        if changes:
            return "Папка с фотографиями отредактирована"
    if log.action == AuditLog.Action.CREATE:
        return "Запись добавлена"
    if log.action == AuditLog.Action.DELETE:
        return "Удаленная запись скрыта из рабочих разделов"
    if changes:
        labels = ", ".join(row["label"] for row in changes[:3])
        if len(changes) > 3:
            labels = f"{labels} и другие поля"
        return f"Запись отредактирована: {labels}"
    return typographic_quotes(log.object_repr) or log.get_action_display()


def audit_location(log):
    if log.action not in {AuditLog.Action.CREATE, AuditLog.Action.UPDATE, AuditLog.Action.DELETE}:
        return []
    parts = []
    if log.territorial_organ_id:
        parts.append(("Территориальный орган", str(log.territorial_organ)))
    table = MODEL_TABLES.get(log.model_name)
    if table:
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


def prepare_log(log):
    log.action_badge = ACTION_BADGES.get(log.action, "audit-action-default")
    log.action_display = ACTION_DISPLAY_LABELS.get(log.action, log.get_action_display())
    log.model_title = model_title(log.model_name)
    log.browser_summary = user_agent_summary(log.user_agent)
    log.change_rows = audit_changes(log)
    log.summary = audit_summary(log)
    log.display_object_repr = typographic_quotes(log.object_repr)
    log.is_object_action = log.action in {AuditLog.Action.CREATE, AuditLog.Action.UPDATE, AuditLog.Action.DELETE}
    log.show_territorial_organ = log.is_object_action and log.territorial_organ_id
    log.location_parts = audit_location(log)
    log.status_history = audit_status_history(log)
    return log


def audit_default_date_from():
    oldest = AuditLog.objects.aggregate(oldest=Min("created_at")).get("oldest")
    return timezone.localtime(oldest).date().isoformat() if oldest else timezone.localdate().isoformat()


def audit_default_date_to():
    return timezone.localdate().isoformat()


def audit_date_value(request, name):
    if name in request.GET:
        return request.GET.get(name, "").strip()
    return audit_default_date_from() if name == "date_from" else audit_default_date_to()


def audit_has_filters(request, date_from, date_to):
    meaningful = {"q", "user", "action", "model", "organ"}
    if any(request.GET.get(name) for name in meaningful):
        return True
    if "date_from" in request.GET and request.GET.get("date_from", "").strip() != audit_default_date_from():
        return True
    if "date_to" in request.GET and request.GET.get("date_to", "").strip() != audit_default_date_to():
        return True
    return False


def filtered_logs(request):
    logs = AuditLog.objects.select_related("user", "territorial_organ").all()
    query = request.GET.get("q", "").strip()
    if query:
        logs = logs.filter(
            Q(object_repr__icontains=query)
            | Q(model_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(ip_address__icontains=query)
            | Q(user_agent__icontains=query)
        )
    if request.GET.get("user"):
        logs = logs.filter(user__username__icontains=request.GET["user"])
    if request.GET.get("action"):
        logs = logs.filter(action=request.GET["action"])
    if request.GET.get("organ"):
        logs = logs.filter(territorial_organ_id=request.GET["organ"])
    if request.GET.get("model"):
        logs = logs.filter(model_name=request.GET["model"])
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)
    return logs


@login_required
@user_passes_test(is_admin)
def audit_log(request):
    logs = filtered_logs(request)
    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get("page"))
    for log in page.object_list:
        prepare_log(log)
    querystring = request.GET.copy()
    querystring.pop("page", None)
    model_names = AuditLog.objects.exclude(model_name="").order_by("model_name").values_list("model_name", flat=True).distinct()
    User = get_user_model()
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    return render(
        request,
        "audit_log.html",
        {
            "page": page,
            "logs": page.object_list,
            "actions": [(value, ACTION_DISPLAY_LABELS.get(value, label)) for value, label in AuditLog.Action.choices],
            "organs": TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).order_by("order_number", "name"),
            "model_names": [(name, model_title(name)) for name in model_names],
            "users": User.objects.filter(is_active=True).order_by("username"),
            "date_from": date_from,
            "date_to": date_to,
            "has_filters": audit_has_filters(request, date_from, date_to),
            "querystring": querystring.urlencode(),
            "total_count": logs.count(),
            "page_links": paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        },
    )


@login_required
@user_passes_test(is_admin)
def audit_detail(request, pk):
    log = prepare_log(get_object_or_404(AuditLog.objects.select_related("user", "territorial_organ"), pk=pk))
    return render(request, "partials/audit_detail.html", {"log": log})
