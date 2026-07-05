from django.contrib.auth import get_user_model
from django.db.models import Min, Q
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan

from apps.audit.models import AuditLog
from .constants import (
    MODEL_TABLES,
    OBJECT_FILTERS,
    OBJECT_MODEL_NAMES,
    PHOTO_OBJECT_MODELS,
    FOLDER_OBJECT_MODELS,
)


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
    return [
        (department.slug, department.name)
        for department in Department.objects.filter(is_active=True).order_by("order_number", "name")
    ]


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
        photo_or_folder_models = PHOTO_OBJECT_MODELS | FOLDER_OBJECT_MODELS
        query |= Q(model_name__in=photo_or_folder_models, new_values__created_department__in=department_values)
        query |= Q(model_name__in=photo_or_folder_models, old_values__created_department__in=department_values)
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


__all__ = [
    "OBJECT_FILTERS",
    "audit_date_value",
    "audit_filter_values",
    "audit_has_filters",
    "audit_multiselect_label",
    "audit_pagination_fields",
    "filtered_logs",
    "is_admin",
    "scope_logs_for_user",
    "scoped_department_options",
    "scoped_organ_queryset",
    "scoped_user_queryset",
    "user_can_view_log",
]
