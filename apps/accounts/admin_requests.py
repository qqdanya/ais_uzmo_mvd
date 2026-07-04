from datetime import date
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import NeedStatus, RequestPhotoLink, RequestStatusHistory
from apps.requests_app.permissions import can_view
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_summary import available_organs_for_user, request_tables, selected_organs
from .business_days import business_days_inclusive, subtract_business_days_inclusive


STATUS_FILTERS = {
    "all": "Все",
    "in_work": "В работе",
    "done": "Исполнено",
    "rejected": "Отклонено",
    "stale": "Зависшие",
}

STATUS_BADGE_CLASSES = {
    NeedStatus.IN_WORK: "status-in_work",
    NeedStatus.DONE: "status-done",
    NeedStatus.REJECTED: "status-rejected",
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


def request_number(obj):
    return getattr(obj, "request_number", None) or str(obj.pk)


def request_title(table, obj):
    title = table.get("title") or obj._meta.verbose_name.title()
    parent_title = table.get("parent_title")
    if parent_title:
        return f"{parent_title}: {title}"
    return title


def date_period_from_request(request):
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


def selected_department(request, options):
    allowed = {item["slug"] for item in options}
    value = request.GET.get("department", "")
    return value if value in allowed else ""


def selected_state(request):
    value = request.GET.get("state", "all")
    return value if value in STATUS_FILTERS else "all"


def selected_per_page(request):
    value = request.GET.get("per_page", "25")
    return int(value) if value in {"25", "50", "100"} else 25


def base_table_queryset(table, organs):
    return table["model"].objects.select_related("territorial_organ").filter(is_deleted=False, territorial_organ__in=organs)


def apply_period(qs, period):
    if period["date_from"]:
        qs = qs.filter(request_date__gte=period["date_from"])
    if period["date_to"]:
        qs = qs.filter(request_date__lte=period["date_to"])
    return qs


def apply_search(qs, query):
    query = (query or "").strip()
    if not query:
        return qs
    filters = Q(request_number__icontains=query) | Q(comment__icontains=query) | Q(territorial_organ__name__icontains=query)
    return qs.filter(filters).distinct()


def apply_state(qs, state):
    stale_before = subtract_business_days_inclusive(timezone.localdate(), 15)
    if state == "in_work":
        return qs.filter(status=NeedStatus.IN_WORK)
    if state == "done":
        return qs.filter(status=NeedStatus.DONE)
    if state == "rejected":
        return qs.filter(status=NeedStatus.REJECTED)
    if state == "stale":
        return qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before)
    return qs


def filtered_queryset(table, organs, filters, *, with_state=True):
    qs = base_table_queryset(table, organs)
    qs = apply_period(qs, filters["period"])
    qs = apply_search(qs, filters["query"])
    if with_state:
        qs = apply_state(qs, filters["state"])
    return qs


def status_counts(tables, organs, filters):
    counts = {key: 0 for key in STATUS_FILTERS}
    stale_before = subtract_business_days_inclusive(timezone.localdate(), 15)
    for table in tables:
        if filters["department"] and table["department"] != filters["department"]:
            continue
        qs = filtered_queryset(table, organs, filters, with_state=False)
        counts["all"] += qs.count()
        counts["in_work"] += qs.filter(status=NeedStatus.IN_WORK).count()
        counts["done"] += qs.filter(status=NeedStatus.DONE).count()
        counts["rejected"] += qs.filter(status=NeedStatus.REJECTED).count()
        counts["stale"] += qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).count()
    return counts


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
    if days > 14:
        return "is-danger"
    if days > 7:
        return "is-warning"
    return "is-normal"


def request_rows(tables, organs, filters):
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    rows = []
    for table in tables:
        if filters["department"] and table["department"] != filters["department"]:
            continue
        qs = filtered_queryset(table, organs, filters).order_by("-request_date", "-created_at", "-pk")
        for obj in qs:
            days = processing_days(obj)
            rows.append(
                {
                    "id": obj.pk,
                    "table_key": table["key"],
                    "number": request_number(obj),
                    "request_date": obj.request_date,
                    "request_date_display": obj.request_date.strftime("%d.%m.%Y") if obj.request_date else "—",
                    "organ": obj.territorial_organ.name,
                    "organ_id": obj.territorial_organ_id,
                    "department_slug": table["department"],
                    "department": departments.get(table["department"], table["department"]),
                    "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
                    "request_type": request_title(table, obj),
                    "status": obj.status,
                    "status_label": obj.get_status_display(),
                    "status_class": STATUS_BADGE_CLASSES.get(obj.status, ""),
                    "days": days,
                    "has_days": days is not None,
                    "days_class": days_class(days),
                    "days_caption": processing_caption(obj, days),
                    "detail_url": reverse("admin_request_detail", kwargs={"table_key": table["key"], "pk": obj.pk}),
                }
            )
    rows.sort(key=lambda item: (item["request_date"] or date.min, item["id"]), reverse=True)
    return rows


def average_completion_days(tables, organs, filters):
    values = []
    for table in tables:
        if filters["department"] and table["department"] != filters["department"]:
            continue
        qs = filtered_queryset(table, organs, filters, with_state=False).filter(status=NeedStatus.DONE)
        for obj in qs:
            days = processing_days(obj)
            if days is not None:
                values.append(days)
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def request_kpis(counts, avg_completion_days):
    return [
        {"label": "В работе", "value": counts.get("in_work", 0), "hint": "текущие заявки", "icon": "bi-hourglass-split"},
        {"label": "Исполнено", "value": counts.get("done", 0), "hint": "по текущим фильтрам", "icon": "bi-check2-circle"},
        {
            "label": "Средний срок исполнения",
            "value": f"{str(avg_completion_days).replace('.', ',')} дн." if avg_completion_days is not None else "—",
            "hint": "по исполненным заявкам",
            "icon": "bi-stopwatch",
        },
        {"label": "Зависшие", "value": counts.get("stale", 0), "hint": "в работе более 14 рабочих дней", "icon": "bi-exclamation-triangle"},
    ]


def query_with(request, **updates):
    query = request.GET.copy()
    query.pop("page", None)
    for key, value in updates.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


def active_filter_chips(filters, selected_organs_list, available_organs, departments):
    chips = []
    if filters["period"]["date_from"] or filters["period"]["date_to"]:
        chips.append(f"Период: {filters['period']['label']}")
    if len(selected_organs_list) != len(available_organs):
        if len(selected_organs_list) == 1:
            chips.append(f"Орган: {selected_organs_list[0].name}")
        else:
            chips.append(f"Органы: {len(selected_organs_list)} из {len(available_organs)}")
    if filters["department"]:
        name = next((item["name"] for item in departments if item["slug"] == filters["department"]), filters["department"])
        chips.append(f"Отдел: {name}")
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    if filters["state"] != "all":
        chips.append(f"Статус: {STATUS_FILTERS[filters['state']]}")
    return chips


def pagination_fields(request):
    fields = []
    for name in ("date_from", "date_to", "department", "state", "q", "per_page"):
        value = request.GET.get(name, "")
        if value:
            fields.append({"name": name, "value": value})
    for value in request.GET.getlist("organ_ids"):
        if value:
            fields.append({"name": "organ_ids", "value": value})
    return fields


def build_requests_context(request):
    tables = list(request_tables())
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    departments = department_options(tables)
    filters = {
        "period": date_period_from_request(request),
        "department": selected_department(request, departments),
        "state": selected_state(request),
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": selected_per_page(request),
    }
    counts = status_counts(tables, organs, filters)
    avg_completion = average_completion_days(tables, organs, filters)
    rows = request_rows(tables, organs, filters)
    paginator = Paginator(rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    selected_ids = {organ.pk for organ in organs}
    return {
        "active_tab": "requests",
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "departments": departments,
        "filters": filters,
        "status_tabs": [
            {
                "key": key,
                "label": label,
                "count": counts.get(key, 0),
                "url": f"?{query_with(request, state=key)}",
                "active": filters["state"] == key,
            }
            for key, label in STATUS_FILTERS.items()
        ],
        "status_options": STATUS_FILTERS.items(),
        "per_page_options": [25, 50, 100],
        "request_kpis": request_kpis(counts, avg_completion),
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_requests_panel"),
        "pagination_fields": pagination_fields(request),
        "active_filter_chips": active_filter_chips(filters, organs, available_organs, departments),
        "reset_url": reverse("admin_requests_panel"),
    }


def table_for_detail(table_key):
    table = TABLE_BY_KEY.get(table_key)
    if not table:
        return None
    field_names = {field.name for field in table["model"]._meta.fields}
    if not {"status", "request_date", "territorial_organ", "is_deleted"}.issubset(field_names):
        return None
    return table


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


def build_request_detail_context(request, table_key, pk):
    table = table_for_detail(table_key)
    if not table:
        raise Http404
    obj = get_object_or_404(table["model"].objects.select_related("territorial_organ", "created_by", "updated_by"), pk=pk, is_deleted=False)
    if not can_view(request.user, obj.territorial_organ):
        raise Http404
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    content_type = ContentType.objects.get_for_model(table["model"], for_concrete_model=False)
    history = RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk).select_related("changed_by")[:8]
    photo_count = RequestPhotoLink.objects.filter(content_type=content_type, object_id=obj.pk).count()
    fields = []
    for name in table.get("fields", []):
        fields.append({"label": field_label(table, name), "value": field_value(obj, name)})
    days = processing_days(obj)
    return {
        "active_tab": "requests",
        "table": table,
        "object": obj,
        "request_number": request_number(obj),
        "request_title": request_title(table, obj),
        "department_name": departments.get(table["department"], table["department"]),
        "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
        "status_class": STATUS_BADGE_CLASSES.get(obj.status, ""),
        "days": days,
        "has_days": days is not None,
        "days_class": days_class(days),
        "days_caption": processing_caption(obj, days),
        "fields": fields,
        "history": history,
        "photo_count": photo_count,
        "back_url": request.META.get("HTTP_REFERER") or reverse("admin_requests_panel"),
        "edit_url": reverse("record_update", kwargs={"organ_id": obj.territorial_organ_id, "table_key": table_key, "pk": obj.pk}),
    }
