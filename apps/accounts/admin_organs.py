from collections import Counter
from datetime import date
from statistics import mean

from django.core.paginator import Paginator
from django.db.models import Max
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto
from apps.requests_app.models import NeedStatus
from apps.requests_app.permissions import can_view

from .admin_requests import (
    DEPARTMENT_ICONS,
    STATUS_BADGE_CLASSES,
    apply_period,
    date_period_from_request,
    days_class,
    department_options,
    processing_caption,
    processing_days,
    query_with,
    multiselect_label,
    request_number,
    request_title,
    selected_per_page,
    selected_values,
)
from .admin_summary import available_organs_for_user, request_tables
from .business_days import subtract_business_days_inclusive
from .admin_thresholds import REQUEST_STALE_WORKDAYS


ORGAN_VIEW_FILTERS = {
    "all": "Все",
    "in_work": "С заявками в работе",
    "stale": "С зависшими",
    "no_activity": "Без активности",
    "best": "Лучшие по срокам",
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


def selected_organs_view(request):
    value = request.GET.get("view", "all")
    return value if value in ORGAN_VIEW_FILTERS else "all"


def selected_request_statuses(request):
    return selected_values(request, "request_status", REQUEST_STATUS_FILTERS.keys())


def selected_departments(request, options):
    return selected_values(request, "department", [item["slug"] for item in options])


def base_organs_for_user(user):
    return available_organs_for_user(user)


def filter_organs_by_search(organs, query):
    query = (query or "").strip().casefold()
    if not query:
        return organs
    return [organ for organ in organs if query in organ.name.casefold() or query in str(organ.order_number).casefold()]


def org_filtered_queryset(table, organ, filters, *, with_request_status=True):
    qs = table["model"].objects.select_related("territorial_organ").filter(is_deleted=False, territorial_organ=organ)
    qs = apply_period(qs, filters["period"])
    statuses = filters.get("request_statuses") or []
    if with_request_status and statuses:
        qs = qs.filter(status__in=[REQUEST_STATUS_TO_MODEL_STATUS[item] for item in statuses if item in REQUEST_STATUS_TO_MODEL_STATUS])
    return qs


def iter_tables(tables, filters):
    for table in tables:
        departments = filters.get("departments") or []
        if departments and table["department"] not in departments:
            continue
        yield table


def completion_values_for_queryset(qs):
    values = []
    for obj in qs.filter(status=NeedStatus.DONE):
        days = processing_days(obj)
        if days is not None:
            values.append(days)
    return values


def request_date_value(obj):
    return getattr(obj, "request_date", None)


def latest_request_date_for_queryset(qs):
    return qs.aggregate(latest=Max("request_date")).get("latest")


def collect_organ_stats(organ, tables, filters):
    stats = Counter()
    completion_values = []
    latest_date = None
    stale_before = subtract_business_days_inclusive(timezone.localdate(), REQUEST_STALE_WORKDAYS + 1)

    for table in iter_tables(tables, filters):
        qs = org_filtered_queryset(table, organ, filters, with_request_status=True)
        stats["total"] += qs.count()
        stats["in_work"] += qs.filter(status=NeedStatus.IN_WORK).count()
        stats["done"] += qs.filter(status=NeedStatus.DONE).count()
        stats["rejected"] += qs.filter(status=NeedStatus.REJECTED).count()
        stats["stale"] += qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).count()
        completion_values.extend(completion_values_for_queryset(qs))
        candidate = latest_request_date_for_queryset(qs)
        if candidate and (latest_date is None or candidate > latest_date):
            latest_date = candidate

    avg_completion = round(mean(completion_values), 1) if completion_values else None
    return {
        "organ": organ,
        "total": stats["total"],
        "in_work": stats["in_work"],
        "done": stats["done"],
        "rejected": stats["rejected"],
        "stale": stats["stale"],
        "avg_completion": avg_completion,
        "avg_completion_display": f"{str(avg_completion).replace('.', ',')} дн." if avg_completion is not None else "—",
        "completion_days_total": sum(completion_values),
        "completion_days_count": len(completion_values),
        "latest_date": latest_date,
        "latest_display": latest_date.strftime("%d.%m.%Y") if latest_date else "—",
        "detail_url": reverse("admin_organ_detail", kwargs={"pk": organ.pk}),
    }


def row_matches_view(row, view):
    if view == "in_work":
        return row["in_work"] > 0
    if view == "stale":
        return row["stale"] > 0
    if view == "no_activity":
        return row["total"] == 0
    if view == "best":
        return row["total"] > 0 and row["avg_completion"] is not None
    return True


def sort_organ_rows(rows, view):
    if view == "best":
        return sorted(rows, key=lambda row: (row["avg_completion"] is None, row["avg_completion"] or 0, -row["done"], row["organ"].order_number, row["organ"].name))
    if view == "stale":
        return sorted(rows, key=lambda row: (-row["stale"], -row["in_work"], row["organ"].order_number, row["organ"].name))
    if view == "in_work":
        return sorted(rows, key=lambda row: (-row["in_work"], -row["total"], row["organ"].order_number, row["organ"].name))
    if view == "no_activity":
        return sorted(rows, key=lambda row: (row["organ"].order_number, row["organ"].name))
    return sorted(rows, key=lambda row: (row["organ"].order_number, row["organ"].name))


def build_organ_rows(organs, tables, filters):
    rows = [collect_organ_stats(organ, tables, filters) for organ in organs]
    rows = [row for row in rows if row_matches_view(row, filters["view"])]
    return sort_organ_rows(rows, filters["view"])


def global_completion_average(rows):
    total = sum(row.get("completion_days_total", 0) for row in rows)
    count = sum(row.get("completion_days_count", 0) for row in rows)
    if not count:
        return None
    return round(total / count, 1)


def build_organs_kpis(all_rows, visible_rows):
    avg_completion = global_completion_average(visible_rows)
    return [
        {"label": "Всего органов", "value": len(visible_rows), "hint": "в текущем списке", "icon": "bi-building"},
        {"label": "Активные органы", "value": sum(1 for row in visible_rows if row["total"] > 0), "hint": "есть заявки", "icon": "bi-activity"},
        {"label": "С зависшими", "value": sum(1 for row in visible_rows if row["stale"] > 0), "hint": f"более {REQUEST_STALE_WORKDAYS} рабочих дней", "icon": "bi-exclamation-triangle"},
        {
            "label": "Средний срок",
            "value": f"{str(avg_completion).replace('.', ',')} дн." if avg_completion is not None else "—",
            "hint": "по исполненным заявкам",
            "icon": "bi-stopwatch",
        },
        {"label": "Без заявок", "value": sum(1 for row in visible_rows if row["total"] == 0), "hint": "по текущим фильтрам", "icon": "bi-inbox"},
    ]


def org_view_counts(all_rows):
    return {
        "all": len(all_rows),
        "in_work": sum(1 for row in all_rows if row["in_work"] > 0),
        "stale": sum(1 for row in all_rows if row["stale"] > 0),
        "no_activity": sum(1 for row in all_rows if row["total"] == 0),
        "best": sum(1 for row in all_rows if row["total"] > 0 and row["avg_completion"] is not None),
    }


def pagination_fields(request):
    fields = []
    for name in ("date_from", "date_to", "view", "q", "per_page"):
        value = request.GET.get(name, "")
        if value:
            fields.append({"name": name, "value": value})
    for name in ("department", "request_status"):
        for value in request.GET.getlist(name):
            if value:
                fields.append({"name": name, "value": value})
    return fields


def active_filter_chips(filters):
    chips = []
    if filters["period"]["date_from"] or filters["period"]["date_to"]:
        chips.append(f"Период: {filters['period']['label']}")
    if filters.get("departments"):
        chips.append(f"Отделы: {filters['department_label']}")
    if filters.get("request_statuses"):
        chips.append(f"Статусы заявок: {filters['request_status_label']}")
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    if filters["view"] != "all":
        chips.append(f"Срез: {ORGAN_VIEW_FILTERS[filters['view']]}")
    return chips


def build_filters(request, departments):
    selected_department_values = selected_departments(request, departments)
    selected_status_values = selected_request_statuses(request)
    department_names = {item["slug"]: item["name"] for item in departments}
    filters = {
        "period": date_period_from_request(request),
        "departments": selected_department_values,
        "department": selected_department_values[0] if len(selected_department_values) == 1 else "",
        "department_label": multiselect_label(selected_department_values, "Все отделы", department_names),
        "request_statuses": selected_status_values,
        "request_status": selected_status_values[0] if len(selected_status_values) == 1 else "all",
        "request_status_label": multiselect_label(selected_status_values, "Все статусы", REQUEST_STATUS_FILTERS),
        "view": selected_organs_view(request),
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": selected_per_page(request),
    }
    filters["per_page_label"] = f"{filters['per_page']} на странице"
    return filters


def build_organs_context(request):
    tables = list(request_tables())
    departments = department_options(tables)
    filters = build_filters(request, departments)
    organs = filter_organs_by_search(base_organs_for_user(request.user), filters["query"])
    all_rows = [collect_organ_stats(organ, tables, filters) for organ in organs]
    visible_rows = sort_organ_rows([row for row in all_rows if row_matches_view(row, filters["view"])], filters["view"])
    counts = org_view_counts(all_rows)
    paginator = Paginator(visible_rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    return {
        "active_tab": "organs",
        "filters": filters,
        "departments": departments,
        "request_status_options": [(key, label) for key, label in REQUEST_STATUS_FILTERS.items() if key != "all"],
        "per_page_options": [50, 100],
        "organs_kpis": build_organs_kpis(all_rows, visible_rows),
        "view_tabs": [
            {
                "key": key,
                "label": label,
                "count": counts.get(key, 0),
                "url": f"?{query_with(request, view=key)}",
                "active": filters["view"] == key,
            }
            for key, label in ORGAN_VIEW_FILTERS.items()
        ],
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_organs_panel"),
        "pagination_fields": pagination_fields(request),
        "active_filter_chips": active_filter_chips(filters),
        "reset_url": reverse("admin_organs_panel"),
    }


def department_stats_for_organ(organ, tables, filters):
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    rows = []
    stale_before = subtract_business_days_inclusive(timezone.localdate(), REQUEST_STALE_WORKDAYS + 1)
    for department in department_options(tables):
        if filters.get("departments") and department["slug"] not in filters["departments"]:
            continue
        stats = Counter()
        completion_values = []
        for table in tables:
            if table["department"] != department["slug"]:
                continue
            qs = org_filtered_queryset(table, organ, filters, with_request_status=True)
            stats["total"] += qs.count()
            stats["in_work"] += qs.filter(status=NeedStatus.IN_WORK).count()
            stats["done"] += qs.filter(status=NeedStatus.DONE).count()
            stats["rejected"] += qs.filter(status=NeedStatus.REJECTED).count()
            stats["stale"] += qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).count()
            completion_values.extend(completion_values_for_queryset(qs))
        avg_completion = round(mean(completion_values), 1) if completion_values else None
        rows.append(
            {
                "slug": department["slug"],
                "name": departments.get(department["slug"], department["name"]),
                "icon": department.get("icon") or DEPARTMENT_ICONS.get(department["slug"], "bi-folder2-open"),
                "total": stats["total"],
                "in_work": stats["in_work"],
                "done": stats["done"],
                "rejected": stats["rejected"],
                "stale": stats["stale"],
                "avg_completion": avg_completion,
                "avg_completion_display": f"{str(avg_completion).replace('.', ',')} дн." if avg_completion is not None else "—",
            }
        )
    return rows


def latest_request_rows_for_organ(organ, tables, filters, limit=15):
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    rows = []
    for table in iter_tables(tables, filters):
        qs = org_filtered_queryset(table, organ, filters, with_request_status=True).order_by("-request_date", "-created_at", "-pk")
        for obj in qs[:limit]:
            days = processing_days(obj)
            rows.append(
                {
                    "id": obj.pk,
                    "table_key": table["key"],
                    "number": request_number(obj),
                    "request_date": obj.request_date,
                    "request_date_display": obj.request_date.strftime("%d.%m.%Y") if obj.request_date else "—",
                    "department": departments.get(table["department"], table["department"]),
                    "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
                    "request_type": request_title(table, obj),
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
    return rows[:limit]


def build_organ_detail_context(request, pk):
    organ = get_object_or_404(TerritorialOrgan.objects.prefetch_related("children"), pk=pk, is_active=True, parent__isnull=True)
    if not can_view(request.user, organ):
        raise Http404
    tables = list(request_tables())
    departments = department_options(tables)
    filters = build_filters(request, departments)
    organ_row = collect_organ_stats(organ, tables, filters)
    children = list(organ.children.filter(is_active=True).order_by("order_number", "name"))
    photo_count = TerritorialOrganPhoto.objects.filter(territorial_organ=organ, is_deleted=False).count()
    return {
        "active_tab": "organs",
        "organ": organ,
        "children": children,
        "photo_count": photo_count,
        "filters": filters,
        "departments": departments,
        "request_status_options": [(key, label) for key, label in REQUEST_STATUS_FILTERS.items() if key != "all"],
        "organ_kpis": [
            {"label": "Всего заявок", "value": organ_row["total"], "hint": filters["period"]["label"], "icon": "bi-inboxes"},
            {"label": "В работе", "value": organ_row["in_work"], "hint": "текущие заявки", "icon": "bi-hourglass-split"},
            {"label": "Исполнено", "value": organ_row["done"], "hint": "по текущим фильтрам", "icon": "bi-check2-circle"},
            {"label": "Зависшие", "value": organ_row["stale"], "hint": f"более {REQUEST_STALE_WORKDAYS} рабочих дней", "icon": "bi-exclamation-triangle"},
            {"label": "Средний срок", "value": organ_row["avg_completion_display"], "hint": "по исполненным заявкам", "icon": "bi-stopwatch"},
        ],
        "department_rows": department_stats_for_organ(organ, tables, filters),
        "latest_requests": latest_request_rows_for_organ(organ, tables, filters),
        "active_filter_chips": active_filter_chips(filters),
        "reset_url": reverse("admin_organ_detail", kwargs={"pk": organ.pk}),
        "back_url": reverse("admin_organs_panel"),
    }
