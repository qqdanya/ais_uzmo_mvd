from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.views import prepare_log
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_requests import selected_per_page
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
        return empty_label or f"Все {noun}"
    if len(items) == total_count:
        return f"Все {noun}"
    if len(items) == 1:
        return str(items[0])
    return f"{len(items)} выбрано"


def format_organs_summary(profile, total_organs, user=None):
    if user is not None and user.is_superuser:
        return "Полный доступ"
    if not profile:
        return "—"
    return rights_summary(profile.allowed_organs.all(), total_organs, "территориальные органы")


def format_departments_summary(profile, total_departments, user=None):
    if user is not None and user.is_superuser:
        return "Полный доступ"
    if not profile:
        return "—"
    return rights_summary(profile.allowed_departments.all(), total_departments, "отделы", empty_label="Отделы не выбраны")


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


def selected_values(request, name, allowed_values):
    allowed = {str(value) for value in allowed_values}
    result = []
    for value in request.GET.getlist(name):
        value = str(value)
        if value in allowed and value not in result:
            result.append(value)
    return result


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
        "per_page": selected_per_page(request),
    }


def multiselect_label(selected_values_list, empty_label, options):
    selected = [str(value) for value in selected_values_list]
    if not selected:
        return empty_label
    if len(selected) == 1:
        return options.get(selected[0], selected[0])
    return f"{len(selected)} выбрано"


def employee_filter_labels(filters, departments, organs):
    return {
        "roles": multiselect_label(filters["roles"], "Все роли", {str(value): label for value, label in UserProfile.Role.choices}),
        "activities": multiselect_label(filters["activities"], "Любая активность", ACTIVITY_OPTIONS),
        "activations": multiselect_label(filters["activations"], "Любой статус", ACTIVATION_OPTIONS),
        "departments": multiselect_label(filters["departments"], "Все отделы", {department.slug: department.name for department in departments}),
        "organs": multiselect_label(filters["organs"], "Все территориальные органы", {str(organ.pk): organ.name for organ in organs}),
        "per_page": f"{filters['per_page']} на странице",
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


def filtered_users(request, users, departments=None, organs=None):
    filters = selected_employee_filters(request, departments=departments, organs=organs)

    if filters["query"]:
        users = users.filter(
            Q(username__icontains=filters["query"])
            | Q(first_name__icontains=filters["query"])
            | Q(last_name__icontains=filters["query"])
            | Q(profile__middle_name__icontains=filters["query"])
        )
    if filters["roles"]:
        users = users.filter(profile__role__in=filters["roles"])
    if filters["departments"]:
        users = users.filter(profile__allowed_departments__slug__in=filters["departments"])
    if filters["organs"]:
        organ_ids = [int(value) for value in filters["organs"]]
        users = users.filter(Q(profile__allowed_organs__pk__in=organ_ids) | Q(profile__allowed_organs__isnull=True))

    activity_states = list(filters["activities"])
    if filters["view"] in {"online", "recent", "offline"}:
        activity_states = [filters["view"]]
    if activity_states:
        users = users.filter(activity_q(activity_states))

    activation_states = list(filters["activations"])
    if filters["view"] == "activation":
        activation_states = ["needs_activation"]
    elif filters["view"] == "blocked":
        activation_states = ["blocked"]
    if activation_states:
        users = users.filter(activation_q(activation_states))
    if filters["view"] == "admins":
        users = users.filter(Q(is_superuser=True) | Q(profile__role=UserProfile.Role.ADMIN))

    return users.distinct()


def tab_count(users, key):
    now = timezone.now()
    if key == "all":
        return users.count()
    if key == "online":
        return users.filter(profile__last_seen_at__gte=now - ONLINE_DELTA).count()
    if key == "recent":
        return users.filter(profile__last_seen_at__lt=now - ONLINE_DELTA, profile__last_seen_at__gte=now - RECENT_DELTA).count()
    if key == "offline":
        return users.filter(Q(profile__last_seen_at__lt=now - RECENT_DELTA) | Q(profile__last_seen_at__isnull=True)).count()
    if key == "activation":
        return users.filter(is_active=True, profile__activation_code__gt="").count()
    if key == "blocked":
        return users.filter(is_active=False).count()
    if key == "admins":
        return users.filter(Q(is_superuser=True) | Q(profile__role=UserProfile.Role.ADMIN)).count()
    return 0


def query_with(request, **updates):
    query = request.GET.copy()
    query.pop("page", None)
    for key, value in updates.items():
        query.pop(key, None)
        if value in (None, ""):
            continue
        if isinstance(value, (list, tuple, set)):
            cleaned = [str(item) for item in value if str(item)]
            if cleaned:
                query.setlist(key, cleaned)
        else:
            query[key] = value
    return query.urlencode()


def pagination_fields(request):
    fields = []
    for name in ("view", "q", "role", "activity", "activation", "department", "organ", "per_page"):
        for value in request.GET.getlist(name):
            if value:
                fields.append({"name": name, "value": value})
    return fields


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

def employee_kpis(users):
    now = timezone.now()
    total = users.count()
    online = users.filter(profile__last_seen_at__gte=now - ONLINE_DELTA).count()
    activation = users.filter(is_active=True, profile__activation_code__gt="").count()
    blocked = users.filter(is_active=False).count()
    admins = users.filter(Q(is_superuser=True) | Q(profile__role=UserProfile.Role.ADMIN)).count()
    return [
        {"key": "total", "label": "Всего сотрудников", "value": total, "hint": "включая заблокированных", "icon": "bi-people"},
        {"key": "online", "label": "Онлайн сейчас", "value": online, "hint": "активность за последнюю минуту", "icon": "bi-broadcast"},
        {"key": "activation", "label": "Ожидают активации", "value": activation, "hint": "ещё не задали пароль", "icon": "bi-person-check"},
        {"key": "blocked", "label": "Заблокированы", "value": blocked, "hint": "вход отключён", "icon": "bi-person-x"},
        {"key": "admins", "label": "Руководители/админы", "value": admins, "hint": "управленческий доступ", "icon": "bi-shield-lock"},
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


def created_requests_count(user, since=None):
    total = 0
    for model in employee_request_models():
        qs = model.objects.filter(is_deleted=False, created_by=user)
        if since:
            qs = qs.filter(created_at__gte=since)
        total += qs.count()
    return total


def employee_activity_stats(users, days=30):
    since = timezone.now() - timedelta(days=days)
    rows = []
    for user in users:
        created_requests = created_requests_count(user, since=since)
        actions = AuditLog.objects.filter(user=user, created_at__gte=since).count()
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
    users = list(employee_queryset())
    kpis = employee_kpis(employee_queryset())
    return {
        "generated_at": timezone.localtime(timezone.now()).strftime("%d.%m.%Y %H:%M:%S"),
        "kpis": {item["key"]: item["value"] for item in kpis},
        "tabs": {key: tab_count(employee_queryset(), key) for key in VIEW_TABS},
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


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_employees_context(request):
    users = employee_queryset()
    departments = list(active_departments())
    organs = list(top_level_organs())
    filters = selected_employee_filters(request, departments=departments, organs=organs)
    filtered = filtered_users(request, users, departments=departments, organs=organs)
    paginator = Paginator(filtered, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    total_organs = len(organs)
    total_departments = len(departments)
    rows = [employee_row(user, total_organs, total_departments) for user in page.object_list]
    return {
        "active_tab": "employees",
        "employee_kpis": employee_kpis(users),
        "activity_chart": employee_activity_stats(list(users), days=30),
        "presence_data_url": reverse("admin_employees_presence_data"),
        "view_tabs": [
            {
                "key": key,
                "label": label,
                "count": tab_count(users, key),
                "url": f"?{query_with(request, view=key)}",
                "active": filters["view"] == key,
            }
            for key, label in VIEW_TABS.items()
        ],
        "filters": filters,
        "filter_labels": employee_filter_labels(filters, departments, organs),
        "employees": rows,
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_employees_panel"),
        "pagination_fields": pagination_fields(request),
        "per_page_options": [50, 100],
        "role_options": UserProfile.Role.choices,
        "activity_options": ACTIVITY_OPTIONS.items(),
        "activation_options": ACTIVATION_OPTIONS.items(),
        "departments": departments,
        "organs": organs,
        "active_filter_chips": active_filter_chips(filters, departments, organs),
        "reset_url": reverse("admin_employees_panel"),
        "create_url": reverse("admin_employee_create"),
    }


class EmployeeForm(forms.ModelForm):
    middle_name = forms.CharField(label="Отчество", required=False, max_length=150)
    role = forms.ChoiceField(label="Роль в системе", choices=UserProfile.Role.choices, initial=UserProfile.Role.OPERATOR)
    allowed_departments = forms.ModelMultipleChoiceField(label="Доступные отделы", queryset=active_departments(), required=False)
    allowed_organs = forms.ModelMultipleChoiceField(label="Доступные территориальные органы", queryset=top_level_organs(), required=False)

    class Meta:
        model = get_user_model()
        fields = (
            "last_name",
            "first_name",
            "middle_name",
            "username",
            "role",
            "allowed_departments",
            "allowed_organs",
            "is_active",
        )
        labels = {
            "last_name": "Фамилия",
            "first_name": "Имя",
            "username": "Логин",
            "is_active": "Аккаунт активен, вход разрешён",
        }
        help_texts = {"username": "Логин выдаётся сотруднику вместе с кодом активации."}

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)
        self.fields["allowed_departments"].queryset = active_departments()
        self.fields["allowed_organs"].queryset = top_level_organs()
        if not self.instance.pk and not self.is_bound:
            self.fields["allowed_departments"].initial = []
            self.fields["allowed_organs"].initial = list(self.fields["allowed_organs"].queryset)
        for name, field in self.fields.items():
            if name in {"allowed_departments", "allowed_organs", "role"}:
                continue
            if name in {"is_active"}:
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control form-control-sm admin-control")
        profile = profile_for(self.instance) if self.instance and self.instance.pk else None
        if profile and not self.is_bound:
            self.fields["middle_name"].initial = profile.middle_name
            self.fields["role"].initial = profile.role
            self.fields["allowed_departments"].initial = profile.allowed_departments.all()
            self.fields["allowed_organs"].initial = profile.allowed_organs.all()

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.current_user and self.instance.pk == self.current_user.pk:
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "Нельзя заблокировать собственную учетную запись.")
            if cleaned.get("role") != UserProfile.Role.ADMIN and not self.instance.is_superuser:
                self.add_error("role", "Нельзя снять с себя административные права.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        is_new = not user.pk
        if is_new:
            user.set_unusable_password()
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.middle_name = self.cleaned_data.get("middle_name", "")
            profile.role = self.cleaned_data.get("role") or UserProfile.Role.OBSERVER
            if is_new or profile.needs_activation:
                profile.ensure_activation_code()
            profile.save()
            profile.allowed_departments.set(self.cleaned_data.get("allowed_departments") or [])
            profile.allowed_organs.set(self.cleaned_data.get("allowed_organs") or [])
        return user


def form_selected_values(form, field_name):
    value = form[field_name].value()
    if value is None:
        return []
    if hasattr(value, "values_list"):
        return [str(item) for item in value.values_list("pk", flat=True)]
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if hasattr(item, "pk"):
                result.append(str(item.pk))
            else:
                result.append(str(item))
        return result
    return [str(value)]


def employee_form_context(request, *, user=None, form=None, mode="create"):
    if form is None:
        form = EmployeeForm(instance=user, current_user=request.user)
    departments = list(active_departments())
    organs = list(top_level_organs())
    selected_departments = form_selected_values(form, "allowed_departments")
    selected_organs = form_selected_values(form, "allowed_organs")
    if mode == "create" and not form.is_bound and not selected_organs:
        selected_organs = [str(organ.pk) for organ in organs]
    role_value_current = (form["role"].value() or UserProfile.Role.OPERATOR)
    role_options = [(str(value), label) for value, label in UserProfile.Role.choices]
    return {
        "active_tab": "employees",
        "mode": mode,
        "form": form,
        "employee": user,
        "profile": profile_for(user) if user else None,
        "departments": departments,
        "organs": organs,
        "selected_departments": selected_departments,
        "selected_organs": selected_organs,
        "selected_role": str(role_value_current),
        "role_options": role_options,
        "role_label": dict(role_options).get(str(role_value_current), "Роль в системе"),
        "department_label": multiselect_label(selected_departments, "Отделы не выбраны", {str(department.pk): department.name for department in departments}),
        "organ_label": multiselect_label(selected_organs, "Все территориальные органы", {str(organ.pk): organ.name for organ in organs}),
        "is_create": mode == "create",
        "back_url": reverse("admin_employees_panel"),
        "title": "Новый сотрудник" if mode == "create" else "Редактирование сотрудника",
        "submit_label": "Создать сотрудника" if mode == "create" else "Сохранить изменения",
    }


def employee_detail_context(request, pk):
    user = get_object_or_404(employee_queryset(), pk=pk)
    profile = profile_for(user)
    total_organs = top_level_organs().count()
    total_departments = active_departments().count()
    logs = list(AuditLog.objects.select_related("user", "territorial_organ").filter(user=user).order_by("-created_at")[:12])
    for log in logs:
        prepare_log(log)
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    recent_actions = AuditLog.objects.filter(user=user, created_at__gte=thirty_days_ago).count()
    recent_created_requests = created_requests_count(user, since=thirty_days_ago)
    return {
        "active_tab": "employees",
        "employee": user,
        "profile": profile,
        "display_name": employee_display_name(user),
        "short_name": employee_short_name(user),
        "role_label": role_label(user),
        "role_class": role_badge_class(user),
        "activity_state": activity_state(profile),
        "activity_label": activity_label(profile),
        "last_seen": last_seen_display(profile),
        "activation_state": activation_state(user),
        "activation_label": activation_label(user),
        "organs_summary": format_organs_summary(profile, total_organs, user),
        "departments_summary": format_departments_summary(profile, total_departments, user),
        "allowed_organs": list(profile.allowed_organs.all()) if profile else [],
        "allowed_departments": list(profile.allowed_departments.all()) if profile else [],
        "all_organs": bool(user.is_superuser or not profile or not profile.allowed_organs.exists()),
        "all_departments": bool(user.is_superuser or (profile and profile.allowed_departments.count() == total_departments and total_departments)),
        "no_departments": bool((not user.is_superuser) and (not profile or not profile.allowed_departments.exists())),
        "has_full_access": user.is_superuser,
        "recent_logs": logs,
        "recent_actions": recent_actions,
        "recent_created_requests": recent_created_requests,
        "edit_url": reverse("admin_employee_edit", kwargs={"pk": user.pk}),
        "back_url": reverse("admin_employees_panel"),
        "presence_data_url": reverse("admin_employees_presence_data"),
        "is_self": request.user.pk == user.pk,
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

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
    if user.pk == request.user.pk and action in {"block", "reset_activation"}:
        messages.error(request, "Нельзя заблокировать или сбросить активацию собственной учетной записи.")
        return redirect("admin_employee_detail", pk=user.pk)
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
