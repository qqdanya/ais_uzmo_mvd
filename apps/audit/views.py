import re
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Min, Q
from django.shortcuts import get_object_or_404, render
from django.http import Http404
from django.urls import reverse
from django.utils.text import capfirst
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import RequestStatusHistory
from apps.requests_app.registry import TABLE_BY_KEY

from .models import AuditLog


SYSTEM_FIELD_NAMES = {"id", "created_at", "updated_at", "created_by", "updated_by", "is_deleted", "audit_event"}
MODEL_HIDDEN_FIELD_NAMES = {
    "TerritorialOrganPhoto": {"created_department"},
    "TerritorialOrganPhotoFolder": {"created_department"},
}
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
PHOTO_OBJECT_MODELS = {"TerritorialOrganPhoto"}
FOLDER_OBJECT_MODELS = {"TerritorialOrganPhotoFolder"}
TABLE_OBJECT_MODELS = set(MODEL_TABLES)
OBJECT_FILTERS = (
    ("table_record", "Запись в таблице", TABLE_OBJECT_MODELS),
    ("photo", "Фотография", PHOTO_OBJECT_MODELS),
    ("folder", "Папка", FOLDER_OBJECT_MODELS),
)
OBJECT_MODEL_NAMES = {key: set(models) for key, _, models in OBJECT_FILTERS}
AUDIT_EVENT_SUMMARIES = {
    "request_status_changed": "Изменен статус заявки",
    "request_photos_attached": "Прикреплены фотографии к заявке",
    "request_photos_detached": "Откреплены фотографии от заявки",
    "tmc_item_added": "Добавлена позиция ТМЦ",
    "tmc_item_removed": "Удалена позиция ТМЦ",
    "tmc_item_quantity_changed": "Изменено количество ТМЦ",
    "tmc_product_created": "Создан товар в справочнике ТМЦ",
}


def department_model_names():
    grouped = {}
    for model_name, config in MODEL_TABLES.items():
        grouped.setdefault(config["department"], set()).add(model_name)
    return grouped


def filtered_model_names(selected_departments, selected_objects):
    model_names = None
    departments = department_model_names()
    if selected_departments:
        model_names = set()
        for department in selected_departments:
            model_names.update(departments.get(department, set()))
    if selected_objects:
        object_models = set()
        for object_key in selected_objects:
            object_models.update(OBJECT_MODEL_NAMES.get(object_key, set()))
        model_names = object_models if model_names is None else model_names & object_models
    return model_names


def audit_department_options():
    return [(department.slug, department.name) for department in Department.objects.filter(is_active=True).order_by("order_number", "name")]


def is_admin(user):
    return user.is_superuser or getattr(getattr(user, "profile", None), "role", "") == "admin"


def profile_department_ids(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return []
    return list(profile.allowed_departments.values_list("pk", flat=True))


def profile_department_slugs(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return []
    return list(profile.allowed_departments.values_list("slug", flat=True))


def profile_organ_ids(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return []
    return list(profile.allowed_organs.values_list("pk", flat=True))


def scoped_user_queryset(user):
    User = get_user_model()
    if is_admin(user):
        return User.objects.filter(is_active=True).select_related("profile").order_by("last_name", "first_name", "username")
    department_ids = profile_department_ids(user)
    if not department_ids:
        return User.objects.filter(pk=user.pk).select_related("profile")
    return (
        User.objects.filter(is_active=True, profile__allowed_departments__in=department_ids)
        .select_related("profile")
        .distinct()
        .order_by("last_name", "first_name", "username")
    )


def scoped_department_options(user):
    departments = Department.objects.filter(is_active=True).order_by("order_number", "name")
    if is_admin(user):
        return [(department.slug, department.name) for department in departments]
    slugs = profile_department_slugs(user)
    if not slugs:
        return []
    return [(department.slug, department.name) for department in departments.filter(slug__in=slugs)]


def scoped_organ_queryset(user):
    organs = TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).order_by("order_number", "name")
    if is_admin(user):
        return organs
    organ_ids = profile_organ_ids(user)
    if not organ_ids:
        return organs
    return organs.filter(pk__in=organ_ids)


def audit_department_q(department_slugs):
    model_names = filtered_model_names(department_slugs, [])
    department_ids = list(Department.objects.filter(slug__in=department_slugs).values_list("pk", flat=True))
    department_values = [str(value) for value in department_ids]
    query = Q()
    if model_names is not None:
        query |= Q(model_name__in=model_names)
    if department_values:
        query |= Q(model_name__in=PHOTO_OBJECT_MODELS | FOLDER_OBJECT_MODELS, new_values__created_department__in=department_values)
        query |= Q(model_name__in=PHOTO_OBJECT_MODELS | FOLDER_OBJECT_MODELS, old_values__created_department__in=department_values)
    return query


def scope_logs_for_user(logs, user):
    if is_admin(user):
        return logs
    scoped_users = scoped_user_queryset(user)
    department_slugs = profile_department_slugs(user)
    organ_ids = profile_organ_ids(user)
    logs = logs.filter(user__in=scoped_users)
    if department_slugs:
        logs = logs.filter(Q(model_name="") | audit_department_q(department_slugs))
    else:
        logs = logs.filter(user=user)
    if organ_ids:
        logs = logs.filter(Q(territorial_organ__isnull=True) | Q(territorial_organ_id__in=organ_ids))
    return logs


def user_can_view_log(user, log):
    if is_admin(user):
        return True
    return scope_logs_for_user(AuditLog.objects.filter(pk=log.pk), user).exists()


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
    hidden_fields = SYSTEM_FIELD_NAMES | MODEL_HIDDEN_FIELD_NAMES.get(log.model_name, set())
    return [key for key in keys if key not in hidden_fields]


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
    audit_event = (log.new_values or {}).get("audit_event")
    if audit_event in AUDIT_EVENT_SUMMARIES:
        return AUDIT_EVENT_SUMMARIES[audit_event]
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
    log.detail_action_text = log.summary
    log.display_object_repr = audit_object_repr(log)
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


def audit_filter_values(request, name):
    return [value for value in request.GET.getlist(name) if value]


def audit_pagination_fields(request, date_from, date_to, show_user_filter=True, show_department_filter=True):
    fields = [
        {"name": "date_from", "value": date_from},
        {"name": "date_to", "value": date_to},
    ]
    names = ["action", "object", "organ"]
    if show_user_filter:
        names.insert(0, "user")
    if show_department_filter:
        names.insert(2 if show_user_filter else 1, "department")
    for name in names:
        fields.extend({"name": name, "value": value} for value in audit_filter_values(request, name))
    return fields


def audit_multiselect_label(selected_values, empty_label, options=None):
    count = len(selected_values)
    if count == 1 and options:
        return options.get(selected_values[0], empty_label)
    return f"Выбрано: {count}" if count else empty_label


def audit_has_filters(request, date_from, date_to, show_user_filter=True, show_department_filter=True):
    meaningful = {"action", "object", "organ"}
    if show_user_filter:
        meaningful.add("user")
    if show_department_filter:
        meaningful.add("department")
    if any(audit_filter_values(request, name) for name in meaningful):
        return True
    if "date_from" in request.GET and request.GET.get("date_from", "").strip() != audit_default_date_from():
        return True
    if "date_to" in request.GET and request.GET.get("date_to", "").strip() != audit_default_date_to():
        return True
    return False


def filtered_logs(request, logs=None, show_user_filter=True, show_department_filter=True):
    if logs is None:
        logs = AuditLog.objects.select_related("user", "territorial_organ").all()
    users = audit_filter_values(request, "user") if show_user_filter else []
    actions = audit_filter_values(request, "action")
    organs = audit_filter_values(request, "organ")
    departments = audit_filter_values(request, "department") if show_department_filter else []
    objects = audit_filter_values(request, "object")
    models = filtered_model_names(departments, objects)
    if users:
        logs = logs.filter(user__username__in=users)
    if actions:
        logs = logs.filter(action__in=actions)
    if organs:
        logs = logs.filter(territorial_organ_id__in=organs)
    if models is not None:
        logs = logs.filter(model_name__in=models)
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)
    return logs


def render_audit_page(request, logs, title, subtitle, reset_url_name, pagination_url_name, show_user_filter=True, show_department_filter=True, show_user_column=True):
    users = list(scoped_user_queryset(request.user))
    actions = [(value, ACTION_DISPLAY_LABELS.get(value, label)) for value, label in AuditLog.Action.choices]
    organs = list(scoped_organ_queryset(request.user))
    department_filters = scoped_department_options(request.user)
    object_filters = [(key, label) for key, label, _ in OBJECT_FILTERS]
    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get("page"))
    for log in page.object_list:
        prepare_log(log)
    querystring = request.GET.copy()
    querystring.pop("page", None)
    querystring.pop("q", None)
    date_from = audit_date_value(request, "date_from")
    date_to = audit_date_value(request, "date_to")
    selected_users = audit_filter_values(request, "user") if show_user_filter else []
    selected_actions = audit_filter_values(request, "action")
    selected_departments = audit_filter_values(request, "department") if show_department_filter else []
    selected_objects = audit_filter_values(request, "object")
    selected_organs = audit_filter_values(request, "organ")
    return render(
        request,
        "audit_log.html",
        {
            "title": title,
            "subtitle": subtitle,
            "page": page,
            "logs": page.object_list,
            "actions": actions,
            "organs": organs,
            "department_filters": department_filters,
            "object_filters": object_filters,
            "users": users,
            "show_user_filter": show_user_filter,
            "show_department_filter": show_department_filter,
            "show_user_column": show_user_column,
            "date_from": date_from,
            "date_to": date_to,
            "selected_users": selected_users,
            "selected_actions": selected_actions,
            "selected_departments": selected_departments,
            "selected_objects": selected_objects,
            "selected_organs": selected_organs,
            "user_filter_label": audit_multiselect_label(selected_users, "Все пользователи", {account.username: user_display_name(account) for account in users}),
            "action_filter_label": audit_multiselect_label(selected_actions, "Все действия", dict(actions)),
            "department_filter_label": audit_multiselect_label(selected_departments, "Все отделы", dict(department_filters)),
            "object_filter_label": audit_multiselect_label(selected_objects, "Все объекты", dict(object_filters)),
            "organ_filter_label": audit_multiselect_label(selected_organs, "Все территориальные органы", {str(organ.pk): organ.name for organ in organs}),
            "has_filters": audit_has_filters(request, date_from, date_to, show_user_filter, show_department_filter),
            "reset_url": reverse(reset_url_name),
            "querystring": querystring.urlencode(),
            "total_count": logs.count(),
            "page_links": paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
            "pagination_url": reverse(pagination_url_name),
            "pagination_fields": audit_pagination_fields(request, date_from, date_to, show_user_filter, show_department_filter),
        },
    )


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
        logs=scope_logs_for_user(AuditLog.objects.select_related("user", "territorial_organ").all(), request.user),
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
    log = prepare_log(get_object_or_404(AuditLog.objects.select_related("user", "territorial_organ"), pk=pk))
    if not user_can_view_log(request.user, log):
        raise Http404
    return render(request, "partials/audit_detail.html", {"log": log})
