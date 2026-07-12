from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_common import DEFAULT_PER_PAGE, build_admin_search_q, build_pagination_fields, multiselect_label, query_with, selected_values
from .models import UserProfile


ONLINE_DELTA = timedelta(minutes=1)
RECENT_DELTA = timedelta(minutes=15)

VIEW_TABS = {
    "all": "Все",
    "online": "Онлайн",
    "recent": "Недавно были",
    "offline": "Оффлайн",
    "activation": "Ожидают активации",
    "blocked": "Заблокированные",
    "admins": "Администраторы",
}

ACTIVITY_OPTIONS = {
    "online": "Онлайн",
    "recent": "Недавно были",
    "offline": "Оффлайн",
    "never": "Не входили",
}

ACTIVATION_OPTIONS = {
    "activated": "Активированы",
    "needs_activation": "Ожидают активации",
    "blocked": "Заблокированы",
}

ROLE_BADGE_CLASSES = {
    UserProfile.Role.ADMIN: "is-neutral",
    UserProfile.Role.OPERATOR: "is-neutral",
    UserProfile.Role.OBSERVER: "is-neutral",
}


# ---------------------------------------------------------------------------
# Common data helpers
# ---------------------------------------------------------------------------

def top_level_organs():
    return TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).order_by("order_number", "name")


def active_departments():
    return Department.objects.filter(is_active=True).order_by("order_number", "name")


def employee_queryset():
    User = get_user_model()
    return (
        User.objects.select_related("profile")
        .prefetch_related("profile__allowed_departments", "profile__allowed_organs")
        .order_by("last_name", "first_name", "username")
    )


def profile_for(user):
    return getattr(user, "profile", None)


def employee_display_name(user):
    profile = profile_for(user)
    if profile:
        return profile.full_display_name
    full_name = user.get_full_name().strip()
    return full_name or user.username


def employee_short_name(user):
    profile = profile_for(user)
    if profile:
        return profile.display_name
    full_name = user.get_full_name().strip()
    return full_name or user.username


def activity_state(profile):
    if not profile or not profile.last_seen_at:
        return "never"
    now = timezone.now()
    if profile.last_seen_at >= now - ONLINE_DELTA:
        return "online"
    if profile.last_seen_at >= now - RECENT_DELTA:
        return "recent"
    return "offline"


def activity_label(profile):
    state = activity_state(profile)
    return {
        "online": "Онлайн",
        "recent": "Недавно был",
        "offline": "Оффлайн",
        "never": "Не входил",
    }.get(state, "Оффлайн")


def last_seen_display(profile):
    if not profile or not profile.last_seen_at:
        return "не входил"
    value = timezone.localtime(profile.last_seen_at)
    now = timezone.localtime(timezone.now())
    delta = now - value
    if delta <= ONLINE_DELTA:
        return "сейчас"
    minutes = max(int(delta.total_seconds() // 60), 1)
    if minutes < 60:
        return f"{minutes} мин. назад"
    if value.date() == now.date():
        return f"сегодня {value:%H:%M}"
    if value.date() == (now.date() - timedelta(days=1)):
        return f"вчера {value:%H:%M}"
    return value.strftime("%d.%m.%Y %H:%M")


def role_label(user):
    profile = profile_for(user)
    if user.is_superuser:
        return "Руководитель"
    return profile.get_role_display() if profile else "Без профиля"


def role_value(user):
    profile = profile_for(user)
    if user.is_superuser:
        return UserProfile.Role.ADMIN
    return getattr(profile, "role", "")


def role_badge_class(user):
    if user.is_superuser:
        return "is-leader"
    return ROLE_BADGE_CLASSES.get(role_value(user), "is-neutral")


def rights_summary(qs, total_count, noun, *, empty_label=None):
    items = list(qs)
    if not items:
        return empty_label or "Доступ не выбран"
    if total_count and len(items) == total_count:
        return f"Все {noun}"
    if len(items) == 1:
        return str(items[0])
    return f"{len(items)} выбрано"


def format_organs_summary(profile, total_organs, user=None):
    if user is not None and user.is_superuser:
        return "Полный доступ"
    if not profile:
        return "—"
    return rights_summary(profile.allowed_organs.all(), total_organs, "территориальные органы", empty_label="Территориальные органы не выбраны")


def format_departments_summary(profile, total_departments, user=None):
    if user is not None and user.is_superuser:
        return "Полный доступ"
    if not profile:
        return "—"
    return rights_summary(profile.allowed_departments.all(), total_departments, "отделы", empty_label="Отделы не выбраны")


def has_all_departments_access(user, profile, total_departments):
    if user.is_superuser:
        return True
    if not profile:
        return False
    selected_count = profile.allowed_departments.count()
    return bool(total_departments and selected_count == total_departments)


def has_all_organs_access(user, profile):
    if user.is_superuser:
        return True
    if not profile:
        return False
    return bool(profile.allowed_organs.exists()) and profile.allowed_organs.count() == top_level_organs().count()


def activation_state(user):
    profile = profile_for(user)
    if not user.is_active:
        return "blocked"
    if profile and profile.needs_activation:
        return "needs_activation"
    return "activated"


def activation_label(user):
    state = activation_state(user)
    return {
        "blocked": "Заблокирован",
        "needs_activation": "Ожидает активации",
        "activated": "Активирован",
    }.get(state, "—")


def employee_row(user, total_organs, total_departments):
    profile = profile_for(user)
    act_state = activity_state(profile)
    role = role_value(user)
    return {
        "user": user,
        "profile": profile,
        "display_name": employee_display_name(user),
        "short_name": employee_short_name(user),
        "role": role,
        "role_label": role_label(user),
        "role_class": role_badge_class(user),
        "activity_state": act_state,
        "activity_label": activity_label(profile),
        "last_seen": last_seen_display(profile),
        "activation_state": activation_state(user),
        "activation_label": activation_label(user),
        "organs_summary": format_organs_summary(profile, total_organs, user),
        "departments_summary": format_departments_summary(profile, total_departments, user),
        "detail_url": reverse("admin_employee_detail", kwargs={"pk": user.pk}),
        "edit_url": reverse("admin_employee_edit", kwargs={"pk": user.pk}),
    }


# ---------------------------------------------------------------------------
# Filters and labels
# ---------------------------------------------------------------------------

def selected_view(request):
    value = request.GET.get("view", "all")
    return value if value in VIEW_TABS else "all"


def selected_employee_filters(request, departments=None, organs=None):
    departments = departments if departments is not None else list(active_departments())
    organs = organs if organs is not None else list(top_level_organs())
    return {
        "view": selected_view(request),
        "query": (request.GET.get("q", "") or "").strip(),
        "roles": selected_values(request, "role", [choice[0] for choice in UserProfile.Role.choices]),
        "activities": selected_values(request, "activity", ACTIVITY_OPTIONS.keys()),
        "activations": selected_values(request, "activation", ACTIVATION_OPTIONS.keys()),
        "departments": selected_values(request, "department", [department.slug for department in departments]),
        "organs": selected_values(request, "organ", [str(organ.pk) for organ in organs]),
        "per_page": DEFAULT_PER_PAGE,
    }


def employee_filter_labels(filters, departments, organs):
    return {
        "roles": multiselect_label(filters["roles"], "Все роли", {str(value): label for value, label in UserProfile.Role.choices}),
        "activities": multiselect_label(filters["activities"], "Любая активность", ACTIVITY_OPTIONS),
        "activations": multiselect_label(filters["activations"], "Любой статус", ACTIVATION_OPTIONS),
        "departments": multiselect_label(filters["departments"], "Все отделы", {department.slug: department.name for department in departments}),
        "organs": multiselect_label(filters["organs"], "Все территориальные органы", {str(organ.pk): organ.name for organ in organs}),
    }


def activity_q(states):
    now = timezone.now()
    query = Q()
    if "online" in states:
        query |= Q(profile__last_seen_at__gte=now - ONLINE_DELTA)
    if "recent" in states:
        query |= Q(profile__last_seen_at__lt=now - ONLINE_DELTA, profile__last_seen_at__gte=now - RECENT_DELTA)
    if "offline" in states:
        query |= Q(profile__last_seen_at__lt=now - RECENT_DELTA)
    if "never" in states:
        query |= Q(profile__last_seen_at__isnull=True)
    return query


def activation_q(states):
    query = Q()
    if "activated" in states:
        query |= Q(is_active=True) & ~Q(profile__activation_code__gt="")
    if "needs_activation" in states:
        query |= Q(is_active=True, profile__activation_code__gt="")
    if "blocked" in states:
        query |= Q(is_active=False)
    return query


def apply_employee_search_filter(users, query):
    if not query:
        return users
    return users.filter(build_admin_search_q(
        ("username", "first_name", "last_name", "profile__middle_name"),
        query,
    ))


def apply_employee_access_filters(users, filters):
    if filters["roles"]:
        users = users.filter(profile__role__in=filters["roles"])
    if filters["departments"]:
        users = users.filter(profile__allowed_departments__slug__in=filters["departments"])
    if filters["organs"]:
        organ_ids = [int(value) for value in filters["organs"]]
        users = users.filter(profile__allowed_organs__pk__in=organ_ids)
    return users


def normalized_activity_states(filters):
    if filters["view"] in {"online", "recent", "offline"}:
        return [filters["view"]]
    return list(filters["activities"])


def normalized_activation_states(filters):
    if filters["view"] == "activation":
        return ["needs_activation"]
    if filters["view"] == "blocked":
        return ["blocked"]
    return list(filters["activations"])


def apply_employee_state_filters(users, filters):
    activity_states = normalized_activity_states(filters)
    if activity_states:
        users = users.filter(activity_q(activity_states))

    activation_states = normalized_activation_states(filters)
    if activation_states:
        users = users.filter(activation_q(activation_states))

    if filters["view"] == "admins":
        users = users.filter(Q(is_superuser=True) | Q(profile__role=UserProfile.Role.ADMIN))
    return users


def filtered_users(request, users, departments=None, organs=None):
    filters = selected_employee_filters(request, departments=departments, organs=organs)
    users = apply_employee_search_filter(users, filters["query"])
    users = apply_employee_access_filters(users, filters)
    users = apply_employee_state_filters(users, filters)
    return users.distinct()


def employee_status_counts(users):
    now = timezone.now()
    counts = users.aggregate(
        total=Count("pk", distinct=True),
        online=Count("pk", distinct=True, filter=Q(profile__last_seen_at__gte=now - ONLINE_DELTA)),
        recent=Count(
            "pk",
            distinct=True,
            filter=Q(profile__last_seen_at__lt=now - ONLINE_DELTA, profile__last_seen_at__gte=now - RECENT_DELTA),
        ),
        offline=Count("pk", distinct=True, filter=Q(profile__last_seen_at__lt=now - RECENT_DELTA) | Q(profile__last_seen_at__isnull=True)),
        activation=Count("pk", distinct=True, filter=Q(is_active=True, profile__activation_code__gt="")),
        blocked=Count("pk", distinct=True, filter=Q(is_active=False)),
        admins=Count("pk", distinct=True, filter=Q(is_superuser=True) | Q(profile__role=UserProfile.Role.ADMIN)),
    )
    return {key: counts.get(key) or 0 for key in ("total", "online", "recent", "offline", "activation", "blocked", "admins")}


def employee_tab_counts(users):
    counts = employee_status_counts(users)
    return {
        "all": counts["total"],
        "online": counts["online"],
        "recent": counts["recent"],
        "offline": counts["offline"],
        "activation": counts["activation"],
        "blocked": counts["blocked"],
        "admins": counts["admins"],
    }


def tab_count(users, key):
    return employee_tab_counts(users).get(key, 0)


def pagination_fields(request):
    return build_pagination_fields(
        request,
        list_fields=("view", "q", "role", "activity", "activation", "department", "organ"),
    )


def active_filter_chips(filters, departments, organs):
    chips = []
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    labels = employee_filter_labels(filters, departments, organs)
    if filters["roles"]:
        chips.append(f"Роли: {labels['roles']}")
    if filters["activities"]:
        chips.append(f"Активность: {labels['activities']}")
    if filters["activations"]:
        chips.append(f"Активация: {labels['activations']}")
    if filters["departments"]:
        chips.append(f"Отделы: {labels['departments']}")
    if filters["organs"]:
        chips.append(f"Органы: {labels['organs']}")
    return chips


# ---------------------------------------------------------------------------
# Metrics and charts
# ---------------------------------------------------------------------------

def employee_kpis(users_or_counts):
    counts = users_or_counts if isinstance(users_or_counts, dict) else employee_status_counts(users_or_counts)
    return [
        {"key": "total", "label": "Всего сотрудников", "value": counts["total"], "hint": "включая заблокированных", "icon": "bi-people"},
        {"key": "online", "label": "Онлайн сейчас", "value": counts["online"], "hint": "активность за последнюю минуту", "icon": "bi-broadcast"},
        {"key": "activation", "label": "Ожидают активации", "value": counts["activation"], "hint": "ещё не задали пароль", "icon": "bi-person-check"},
        {"key": "blocked", "label": "Заблокированы", "value": counts["blocked"], "hint": "вход отключён", "icon": "bi-person-x"},
        {"key": "admins", "label": "Руководители и администраторы", "value": counts["admins"], "hint": "расширенные права доступа", "icon": "bi-shield-lock"},
    ]


def employee_request_models():
    """Models that represent actual заявки, not historical asset/current-state rows."""
    seen = set()
    for table in TABLE_BY_KEY.values():
        model = table["model"]
        if model in seen:
            continue
        seen.add(model)
        field_names = {field.name for field in model._meta.fields}
        if {"request_date", "status", "created_by", "is_deleted"}.issubset(field_names):
            yield model


def created_requests_counts_by_user(users, since=None):
    """Grouped counterpart of created_requests_count: one query per model instead of one per (user, model) pair.

    Looping created_requests_count() once per employee turns O(employees) into
    O(employees * request_models) queries on the employees list/activity chart.
    Grouping by created_by inside one query per model keeps it at O(request_models).
    """
    user_ids = [user.pk for user in users]
    totals = {user_id: 0 for user_id in user_ids}
    for model in employee_request_models():
        qs = model.objects.filter(is_deleted=False, created_by_id__in=user_ids)
        if since:
            qs = qs.filter(created_at__gte=since)
        for row in qs.values("created_by_id").annotate(total=Count("pk")):
            created_by_id = row["created_by_id"]
            if created_by_id in totals:
                totals[created_by_id] += row["total"]
    return totals


def created_requests_count(user, since=None):
    return created_requests_counts_by_user([user], since=since)[user.pk]


def employee_activity_stats(users, days=30):
    since = timezone.now() - timedelta(days=days)
    users = list(users)
    created_counts = created_requests_counts_by_user(users, since=since)
    action_counts = dict(
        AuditLog.objects.filter(user_id__in=[user.pk for user in users], created_at__gte=since)
        .values("user_id")
        .annotate(total=Count("pk"))
        .values_list("user_id", "total")
    )
    rows = []
    for user in users:
        created_requests = created_counts.get(user.pk, 0)
        actions = action_counts.get(user.pk, 0)
        if not created_requests and not actions:
            continue
        rows.append(
            {
                "user": user,
                "name": employee_short_name(user),
                "created_requests": created_requests,
                "actions": actions,
                "total": created_requests + actions,
            }
        )
    rows.sort(key=lambda row: (row["total"], row["created_requests"], row["actions"], row["name"]), reverse=True)
    rows = rows[:10]
    max_created = max((row["created_requests"] for row in rows), default=0)
    max_actions = max((row["actions"] for row in rows), default=0)
    for row in rows:
        row["created_width"] = round((row["created_requests"] / max_created) * 100, 1) if max_created else 0
        row["actions_width"] = round((row["actions"] / max_actions) * 100, 1) if max_actions else 0
        row["detail_url"] = reverse("admin_employee_detail", kwargs={"pk": row["user"].pk})
    return rows


def employee_presence_payload():
    users_qs = employee_queryset()
    users = list(users_qs)
    counts = employee_status_counts(users_qs)
    kpis = employee_kpis(counts)
    return {
        "generated_at": timezone.localtime(timezone.now()).strftime("%d.%m.%Y %H:%M:%S"),
        "kpis": {item["key"]: item["value"] for item in kpis},
        "tabs": {key: counts.get("total" if key == "all" else key, 0) for key in VIEW_TABS},
        "employees": [
            {
                "id": user.pk,
                "activity_state": activity_state(profile_for(user)),
                "activity_label": activity_label(profile_for(user)),
                "last_seen": last_seen_display(profile_for(user)),
                "activation_state": activation_state(user),
                "activation_label": activation_label(user),
            }
            for user in users
        ],
    }


def employee_view_tabs(request, filters, counts):
    tab_counts = {key: counts.get("total" if key == "all" else key, 0) for key in VIEW_TABS}
    return [
        {
            "key": key,
            "label": label,
            "count": tab_counts[key],
            "url": f"?{query_with(request, view=key)}",
            "active": filters["view"] == key,
        }
        for key, label in VIEW_TABS.items()
    ]
