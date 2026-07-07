from statistics import mean

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.directory.models import Department
from apps.requests_app.models import NeedStatus, RequestStatusHistory

from .admin_thresholds import get_request_stale_workdays
from .business_days import business_days_inclusive


PER_PAGE_CHOICES = {"50", "100"}
DEFAULT_PER_PAGE = 50

STATUS_BADGE_CLASSES = {
    NeedStatus.IN_WORK: "status-in_work",
    NeedStatus.DONE: "status-done",
    NeedStatus.REJECTED: "status-rejected",
}

REQUEST_STATUS_FILTERS = {
    "all": "Все статусы",
    "in_work": "В работе",
    "done": "Исполнено",
    "rejected": "Отклонено",
}

REQUEST_STATUS_TO_MODEL_STATUS = {
    "in_work": NeedStatus.IN_WORK,
    "done": NeedStatus.DONE,
    "rejected": NeedStatus.REJECTED,
}

DEPARTMENT_ICONS = {
    "tmc": "bi-box-seam",
    "transport": "bi-truck",
    "fire": "bi-fire",
    "antiterror": "bi-shield-lock",
    "citsizi": "bi-router",
    "uoto": "bi-building",
}

COMPUTED_FIELD_LABELS = {
    "items_summary": "Наименования",
}


def date_period_from_request(request):
    """Return normalized date range filters and a human-readable label."""
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    if date_from and date_to:
        label = f"{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}"
    elif date_from:
        label = f"с {date_from:%d.%m.%Y}"
    elif date_to:
        label = f"по {date_to:%d.%m.%Y}"
    else:
        label = "за всё время"
    return {"date_from": date_from, "date_to": date_to, "label": label}


def selected_per_page(request):
    value = request.GET.get("per_page", str(DEFAULT_PER_PAGE))
    return int(value) if value in PER_PAGE_CHOICES else DEFAULT_PER_PAGE


def selected_values(request, name, allowed_values, *, drop_all=True):
    allowed = {str(value) for value in allowed_values}
    result = []
    for value in request.GET.getlist(name):
        value = str(value)
        if drop_all and value == "all":
            continue
        if value in allowed and value not in result:
            result.append(value)
    return result


def selected_request_statuses(request):
    return selected_values(request, "request_status", REQUEST_STATUS_FILTERS.keys())


def row_matches_view(row, view):
    """Match a department/organ summary row against a dashboard view tab."""
    if view == "in_work":
        return row["in_work"] > 0
    if view == "stale":
        return row["stale"] > 0
    if view == "no_activity":
        return row["total"] == 0
    if view == "best":
        return row["total"] > 0 and row["avg_completion"] is not None
    return True


def filter_by_request_statuses(qs, filters, *, with_request_status=True):
    """Apply the shared request-status filter used by department/organ dashboards."""
    statuses = filters.get("request_statuses") or []
    if with_request_status and statuses:
        qs = qs.filter(status__in=[REQUEST_STATUS_TO_MODEL_STATUS[item] for item in statuses if item in REQUEST_STATUS_TO_MODEL_STATUS])
    return qs


def multiselect_label(selected_values_list, empty_label, options):
    selected = [str(value) for value in selected_values_list if str(value)]
    if not selected:
        return empty_label
    if len(selected) == 1:
        return options.get(selected[0], selected[0])
    return f"{len(selected)} выбрано"


def search_terms(query):
    """Return safe text variants for case-insensitive admin search on SQLite/PostgreSQL.

    SQLite does not reliably handle non-ASCII case-insensitive LIKE, so we keep
    a small set of case variants while still letting the database do the
    filtering instead of iterating through full Python object lists.
    """
    value = (query or "").strip()
    if not value:
        return []
    variants = {
        value,
        value.lower(),
        value.upper(),
        value.title(),
        value.capitalize(),
        value.casefold(),
    }
    return [item for item in variants if item]


def build_admin_search_q(text_fields, query, *, numeric_fields=()):
    """Build an ORM search condition for admin list filters.

    `text_fields` are searched with icontains over a bounded set of case
    variants. `numeric_fields` are matched exactly when the query is numeric.
    """
    condition = Q()
    for term in search_terms(query):
        for field_name in text_fields:
            condition |= Q(**{f"{field_name}__icontains": term})

    value = (query or "").strip()
    if value.isdigit():
        number = int(value)
        for field_name in numeric_fields:
            condition |= Q(**{field_name: number})
    return condition


def filter_model_objects_by_search(objects, query, *, text_fields, numeric_fields=()):
    """Filter an already permission-scoped model object list through the ORM.

    Admin pages often receive lists after applying access checks. This helper
    preserves that scoped list and its order, but delegates text matching to the
    database using pk__in instead of scanning all objects with Python casefold().
    """
    items = list(objects)
    if not (query or "").strip() or not items:
        return items

    model = items[0].__class__
    pks = [item.pk for item in items]
    condition = build_admin_search_q(text_fields, query, numeric_fields=numeric_fields)
    matched_ids = set(model.objects.filter(pk__in=pks).filter(condition).values_list("pk", flat=True))
    return [item for item in items if item.pk in matched_ids]


def filter_department_options_by_search(departments, query):
    """Filter department option dictionaries through the Department queryset."""
    items = list(departments)
    if not (query or "").strip() or not items:
        return items

    slugs = [item["slug"] for item in items]
    condition = build_admin_search_q(("name", "slug", "description"), query, numeric_fields=("order_number",))
    matched_slugs = set(
        Department.objects.filter(is_active=True, slug__in=slugs)
        .filter(condition)
        .values_list("slug", flat=True)
    )
    return [item for item in items if item["slug"] in matched_slugs]


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


def request_number(obj):
    return getattr(obj, "request_number", None) or str(obj.pk)


def request_title(table, obj):
    title = table.get("title") or obj._meta.verbose_name.title()
    parent_title = table.get("parent_title")
    if parent_title:
        return f"{parent_title}: {title}"
    return title


def department_options(tables):
    slugs = []
    for table in tables:
        slug = table["department"]
        if slug not in slugs:
            slugs.append(slug)
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    return [
        {
            "slug": slug,
            "name": departments.get(slug, slug),
            "icon": DEPARTMENT_ICONS.get(slug, "bi-folder2-open"),
        }
        for slug in slugs
    ]



def request_status_counts(qs, *, stale_before=None):
    """Return request counters with one aggregate query for a prepared queryset."""
    aggregations = {
        "total": Count("pk"),
        "in_work": Count("pk", filter=Q(status=NeedStatus.IN_WORK)),
        "done": Count("pk", filter=Q(status=NeedStatus.DONE)),
        "rejected": Count("pk", filter=Q(status=NeedStatus.REJECTED)),
    }
    if stale_before is not None:
        aggregations["stale"] = Count("pk", filter=Q(status=NeedStatus.IN_WORK, request_date__lte=stale_before))
    counts = qs.aggregate(**aggregations)
    if stale_before is None:
        counts["stale"] = 0
    return {key: counts.get(key) or 0 for key in ("total", "in_work", "done", "rejected", "stale")}


def add_status_counts(total_counts, counts):
    """Add request counters from one table to a mutable totals mapping."""
    for key in ("total", "in_work", "done", "rejected", "stale"):
        total_counts[key] += counts.get(key, 0)


def _own_completion_date(obj):
    for field_name in ("completed_at", "due_date"):
        value = getattr(obj, field_name, None)
        if value:
            return value
    return None


def _bulk_history_completion_dates(objects):
    """Batch-fetch the best RequestStatusHistory completion date per object.

    Avoids one RequestStatusHistory query per row (the previous per-object
    object_completion_date() call) when completed_at/due_date is missing.
    """
    if not objects:
        return {}
    content_type = ContentType.objects.get_for_model(objects[0]._meta.model, for_concrete_model=False)
    history_qs = RequestStatusHistory.objects.filter(
        content_type=content_type,
        object_id__in=[obj.pk for obj in objects],
        new_status=NeedStatus.DONE,
    ).order_by("object_id", "-completed_at", "-changed_at", "-pk")
    dates = {}
    for history in history_qs:
        if history.object_id not in dates:
            dates[history.object_id] = history.completed_at or history.changed_at.date()
    return dates


def completion_values_for_queryset(qs):
    """Return processing-day values for completed requests in a queryset."""
    done_objects = list(qs.filter(status=NeedStatus.DONE))
    missing = [obj for obj in done_objects if _own_completion_date(obj) is None]
    history_dates = _bulk_history_completion_dates(missing)
    values = []
    for obj in done_objects:
        end_date = _own_completion_date(obj) or history_dates.get(obj.pk)
        if not end_date:
            continue
        days = business_days_inclusive(obj.request_date, end_date)
        if days is not None:
            values.append(days)
    return values


def completion_average(values):
    return round(mean(values), 1) if values else None


def completion_display(value):
    return f"{str(value).replace('.', ',')} дн." if value is not None else "—"


def latest_request_date_for_queryset(qs):
    return qs.aggregate(latest=Max("request_date")).get("latest")


def global_completion_average(rows):
    total = sum(row.get("completion_days_total", 0) for row in rows)
    count = sum(row.get("completion_days_count", 0) for row in rows)
    if not count:
        return None
    return round(total / count, 1)


def build_pagination_fields(request, scalar_fields=(), list_fields=(), flag_fields=()):
    fields = []
    for name in scalar_fields:
        value = request.GET.get(name, "")
        if value:
            fields.append({"name": name, "value": value})
    for name in list_fields:
        for value in request.GET.getlist(name):
            if value:
                fields.append({"name": name, "value": value})
    for name in flag_fields:
        if request.GET.get(name) == "1":
            fields.append({"name": name, "value": "1"})
    return fields

def apply_period(qs, period):
    if period["date_from"]:
        qs = qs.filter(request_date__gte=period["date_from"])
    if period["date_to"]:
        qs = qs.filter(request_date__lte=period["date_to"])
    return qs


def object_completion_date(obj):
    """Return the best known completion date for an executed request."""
    for field_name in ("completed_at", "due_date"):
        value = getattr(obj, field_name, None)
        if value:
            return value
    content_type = ContentType.objects.get_for_model(obj._meta.model, for_concrete_model=False)
    history = (
        RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk, new_status=NeedStatus.DONE)
        .order_by("-completed_at", "-changed_at", "-pk")
        .first()
    )
    if history:
        return history.completed_at or history.changed_at.date()
    return None


def object_rejected_date(obj):
    """Return the date when a request was rejected, if it can be determined."""
    content_type = ContentType.objects.get_for_model(obj._meta.model, for_concrete_model=False)
    history = (
        RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk, new_status=NeedStatus.REJECTED)
        .order_by("-changed_at", "-pk")
        .first()
    )
    return history.changed_at.date() if history else None


def processing_days(obj):
    request_date = getattr(obj, "request_date", None)
    status = getattr(obj, "status", None)
    if not request_date:
        return None
    if status == NeedStatus.IN_WORK:
        end_date = timezone.localdate()
    elif status == NeedStatus.DONE:
        end_date = object_completion_date(obj)
    elif status == NeedStatus.REJECTED:
        end_date = object_rejected_date(obj)
    else:
        end_date = None
    if not end_date:
        return None
    # Срок обработки считаем по рабочим дням Пн–Пт включительно.
    # День поступления заявки входит в срок, поэтому "сегодня → сегодня" = 1 рабочий день.
    return business_days_inclusive(request_date, end_date)


def processing_caption(obj, days):
    if days is None:
        return ""
    if getattr(obj, "status", None) == NeedStatus.IN_WORK:
        return "в работе"
    if getattr(obj, "status", None) == NeedStatus.DONE:
        return "на исполнение"
    if getattr(obj, "status", None) == NeedStatus.REJECTED:
        return "до отклонения"
    return ""


def days_class(days):
    if days is None:
        return ""
    if days > get_request_stale_workdays():
        return "is-danger"
    if days > 7:
        return "is-warning"
    return "is-normal"


def field_label(table, field_name):
    if field_name in COMPUTED_FIELD_LABELS:
        return COMPUTED_FIELD_LABELS[field_name]
    try:
        return table["model"]._meta.get_field(field_name).verbose_name.capitalize()
    except Exception:
        return field_name.replace("_", " ").capitalize()


def field_value(obj, field_name):
    display = getattr(obj, f"get_{field_name}_display", None)
    if callable(display):
        return display()
    value = getattr(obj, field_name, "")
    if callable(value):
        value = value()
    if value is None or value == "":
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return value
