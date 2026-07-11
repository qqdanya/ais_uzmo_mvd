from collections import Counter
from datetime import date

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto
from apps.requests_app.permissions import can_view

from .admin_common import (
    DEFAULT_PER_PAGE,
    DEPARTMENT_ICONS,
    REQUEST_STATUS_FILTERS,
    STATUS_BADGE_CLASSES,
    add_status_counts,
    apply_period,
    build_pagination_fields,
    completion_average_from_totals,
    completion_display,
    completion_totals_for_queryset,
    completion_totals_by_organ_for_queryset,
    date_period_from_request,
    days_class,
    filter_by_request_statuses,
    filter_model_objects_by_search,
    department_options,
    global_completion_average,
    latest_request_date_for_queryset,
    latest_request_dates_by_organ,
    multiselect_label,
    processing_caption,
    processing_days,
    query_with,
    request_number,
    request_status_counts,
    request_status_counts_by_organ,
    request_title,
    row_matches_view,
    selected_request_statuses,
    selected_values,
)
from .admin_requests import attach_processing_end_dates
from .admin_summary import available_organs_for_user, request_tables
from .business_days import subtract_business_days_inclusive
from .admin_thresholds import get_request_stale_workdays


ORGAN_VIEW_FILTERS = {
    "all": "Все",
    "in_work": "С заявками в работе",
    "stale": "С зависшими",
    "no_activity": "Без активности",
    "best": "Лучшие по срокам",
}


def selected_organs_view(request):
    value = request.GET.get("view", "all")
    return value if value in ORGAN_VIEW_FILTERS else "all"


def selected_departments(request, options):
    return selected_values(request, "department", [item["slug"] for item in options])


def base_organs_for_user(user):
    return available_organs_for_user(user)


def filter_organs_by_search(organs, query):
    return filter_model_objects_by_search(
        organs,
        query,
        text_fields=("name",),
        numeric_fields=("order_number",),
    )


def org_filtered_queryset(table, organ, filters, *, with_request_status=True):
    qs = table["model"].objects.select_related("territorial_organ").filter(is_deleted=False, territorial_organ=organ)
    qs = apply_period(qs, filters["period"])
    return filter_by_request_statuses(qs, filters, with_request_status=with_request_status)


def all_organs_filtered_queryset(table, organs, filters, *, with_request_status=True):
    qs = table["model"].objects.filter(is_deleted=False, territorial_organ__in=organs)
    qs = apply_period(qs, filters["period"])
    return filter_by_request_statuses(qs, filters, with_request_status=with_request_status)


def iter_tables(tables, filters):
    for table in tables:
        departments = filters.get("departments") or []
        if departments and table["department"] not in departments:
            continue
        yield table


def organ_stats_row(organ, stats, completion_days_total, completion_days_count, latest_date):
    avg_completion = completion_average_from_totals(completion_days_total, completion_days_count)
    return {
        "organ": organ,
        "total": stats["total"],
        "in_work": stats["in_work"],
        "done": stats["done"],
        "rejected": stats["rejected"],
        "stale": stats["stale"],
        "avg_completion": avg_completion,
        "avg_completion_display": completion_display(avg_completion),
        "completion_days_total": completion_days_total,
        "completion_days_count": completion_days_count,
        "latest_date": latest_date,
        "latest_display": latest_date.strftime("%d.%m.%Y") if latest_date else "—",
        "detail_url": reverse("admin_organ_detail", kwargs={"pk": organ.pk}),
    }


def collect_all_organ_stats(organs, tables, filters):
    """Build one stats row per organ in O(tables) queries instead of O(organs * tables).

    Looping collect_organ_stats() once per organ (the previous approach) means
    e.g. 37 organs x 12 tables x ~3 queries each = 700+ queries for the organs
    dashboard. Grouping by territorial_organ inside one query per table gets
    the same numbers in roughly 2-3 queries per table, regardless of how many
    organs are selected.
    """
    stale_before = filters["stale_before"]
    buckets = {organ.pk: {"stats": Counter(), "completion_days_total": 0, "completion_days_count": 0, "latest_date": None} for organ in organs}

    for table in iter_tables(tables, filters):
        qs = all_organs_filtered_queryset(table, organs, filters, with_request_status=True)

        counts_by_organ = request_status_counts_by_organ(qs, stale_before=stale_before)
        for organ_id, counts in counts_by_organ.items():
            bucket = buckets.get(organ_id)
            if bucket is not None:
                add_status_counts(bucket["stats"], counts)

        completion_by_organ = completion_totals_by_organ_for_queryset(qs, table["key"])
        for organ_id, totals in completion_by_organ.items():
            bucket = buckets.get(organ_id)
            if bucket is not None:
                bucket["completion_days_total"] += totals["total"]
                bucket["completion_days_count"] += totals["count"]

        latest_by_organ = latest_request_dates_by_organ(qs)
        for organ_id, latest in latest_by_organ.items():
            bucket = buckets.get(organ_id)
            if bucket is not None and latest and (bucket["latest_date"] is None or latest > bucket["latest_date"]):
                bucket["latest_date"] = latest

    return {
        organ.pk: organ_stats_row(
            organ,
            buckets[organ.pk]["stats"],
            buckets[organ.pk]["completion_days_total"],
            buckets[organ.pk]["completion_days_count"],
            buckets[organ.pk]["latest_date"],
        )
        for organ in organs
    }


def collect_organ_stats(organ, tables, filters):
    return collect_all_organ_stats([organ], tables, filters)[organ.pk]


def sort_organ_rows(rows, view):
    default_key = lambda row: (row["organ"].order_number, row["organ"].name)
    if view == "best":
        return sorted(rows, key=lambda row: (row["avg_completion"] is None, row["avg_completion"] or 0, -row["done"], *default_key(row)))
    if view == "stale":
        return sorted(rows, key=lambda row: (-row["stale"], -row["in_work"], *default_key(row)))
    if view == "in_work":
        return sorted(rows, key=lambda row: (-row["in_work"], -row["total"], *default_key(row)))
    return sorted(rows, key=default_key)


def visible_organ_rows(rows, view):
    rows = [row for row in rows if row_matches_view(row, view)]
    return sort_organ_rows(rows, view)


def build_organs_kpis(all_rows, visible_rows):
    avg_completion = global_completion_average(visible_rows)
    return [
        {"label": "Всего органов", "value": len(visible_rows), "hint": "в текущем списке", "icon": "bi-building"},
        {"label": "Активные органы", "value": sum(1 for row in visible_rows if row["total"] > 0), "hint": "есть заявки", "icon": "bi-activity"},
        {"label": "С зависшими", "value": sum(1 for row in visible_rows if row["stale"] > 0), "hint": f"более {get_request_stale_workdays()} рабочих дней", "icon": "bi-exclamation-triangle"},
        {
            "label": "Средний срок",
            "value": completion_display(avg_completion),
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
    return build_pagination_fields(
        request,
        scalar_fields=("date_from", "date_to", "view", "q"),
        list_fields=("department", "request_status"),
    )


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
        "per_page": DEFAULT_PER_PAGE,
        "stale_before": subtract_business_days_inclusive(timezone.localdate(), get_request_stale_workdays() + 1),
    }
    return filters


def build_organs_context(request):
    tables = list(request_tables())
    departments = department_options(tables)
    filters = build_filters(request, departments)
    organs = filter_organs_by_search(base_organs_for_user(request.user), filters["query"])
    stats_by_organ = collect_all_organ_stats(organs, tables, filters)
    all_rows = [stats_by_organ[organ.pk] for organ in organs]
    visible_rows = visible_organ_rows(all_rows, filters["view"])
    counts = org_view_counts(all_rows)
    paginator = Paginator(visible_rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    return {
        "active_tab": "organs",
        "filters": filters,
        "departments": departments,
        "request_status_options": [(key, label) for key, label in REQUEST_STATUS_FILTERS.items() if key != "all"],
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
    stale_before = filters["stale_before"]
    for department in department_options(tables):
        if filters.get("departments") and department["slug"] not in filters["departments"]:
            continue
        stats = Counter()
        completion_days_total = 0
        completion_days_count = 0
        for table in tables:
            if table["department"] != department["slug"]:
                continue
            qs = org_filtered_queryset(table, organ, filters, with_request_status=True)
            add_status_counts(stats, request_status_counts(qs, stale_before=stale_before))
            table_days, table_count = completion_totals_for_queryset(qs, table["key"])
            completion_days_total += table_days
            completion_days_count += table_count
        avg_completion = completion_average_from_totals(completion_days_total, completion_days_count)
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
                "avg_completion_display": completion_display(avg_completion),
            }
        )
    return rows


def latest_request_rows_for_organ(organ, tables, filters, limit=15):
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    rows = []
    for table in iter_tables(tables, filters):
        qs = org_filtered_queryset(table, organ, filters, with_request_status=True).order_by("-request_date", "-created_at", "-pk")
        objects = list(qs[:limit])
        # Without this, processing_days() falls back to one RequestStatusHistory
        # query per done/rejected row that lacks its own completion date.
        attach_processing_end_dates(table, objects)
        for obj in objects:
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
            {"label": "Зависшие", "value": organ_row["stale"], "hint": f"более {get_request_stale_workdays()} рабочих дней", "icon": "bi-exclamation-triangle"},
            {"label": "Средний срок", "value": organ_row["avg_completion_display"], "hint": "по исполненным заявкам", "icon": "bi-stopwatch"},
        ],
        "department_rows": department_stats_for_organ(organ, tables, filters),
        "latest_requests": latest_request_rows_for_organ(organ, tables, filters),
        "active_filter_chips": active_filter_chips(filters),
        "reset_url": reverse("admin_organ_detail", kwargs={"pk": organ.pk}),
        "back_url": reverse("admin_organs_panel"),
    }
