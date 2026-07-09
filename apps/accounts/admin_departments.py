from collections import Counter
from datetime import date

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department

from .admin_common import (
    DEPARTMENT_ICONS,
    REQUEST_STATUS_FILTERS,
    STATUS_BADGE_CLASSES,
    add_status_counts,
    apply_period,
    build_pagination_fields,
    completion_average_from_totals,
    completion_display,
    completion_totals_by_organ_for_queryset,
    completion_totals_for_queryset,
    date_period_from_request,
    days_class,
    filter_by_request_statuses,
    filter_department_options_by_search,
    department_options,
    global_completion_average,
    latest_request_date_for_queryset,
    multiselect_label,
    processing_caption,
    processing_days,
    query_with,
    request_number,
    request_status_counts,
    request_status_counts_by_organ,
    request_title,
    row_matches_view,
    selected_per_page,
    selected_request_statuses,
)
from .admin_summary import available_organs_for_user, request_tables, selected_organs
from .business_days import subtract_business_days_inclusive
from .admin_thresholds import get_request_stale_workdays


DEPARTMENT_VIEW_FILTERS = {
    "all": "Все",
    "in_work": "С заявками в работе",
    "stale": "С зависшими",
    "no_activity": "Без активности",
    "best": "Лучшие по срокам",
}


def selected_department_view(request):
    value = request.GET.get("view", "all")
    return value if value in DEPARTMENT_VIEW_FILTERS else "all"


def selected_department_slug(request, departments):
    allowed = {item["slug"] for item in departments}
    value = request.GET.get("department", "")
    return value if value in allowed else ""


def department_name_by_slug(departments):
    return {item["slug"]: item["name"] for item in departments}


def department_icon(slug):
    return DEPARTMENT_ICONS.get(slug, "bi-folder2-open")


def filter_departments_by_search(departments, query):
    return filter_department_options_by_search(departments, query)


def tables_for_department(tables, department_slug):
    return [table for table in tables if table["department"] == department_slug]


def department_filtered_queryset(table, organs, filters, *, with_request_status=True):
    qs = table["model"].objects.select_related("territorial_organ").filter(is_deleted=False, territorial_organ__in=organs)
    qs = apply_period(qs, filters["period"])
    return filter_by_request_statuses(qs, filters, with_request_status=with_request_status)


def collect_department_stats(department, tables, organs, filters):
    stats = Counter()
    completion_days_total = 0
    completion_days_count = 0
    active_organ_ids = set()
    latest_date = None
    stale_before = filters["stale_before"]

    for table in tables_for_department(tables, department["slug"]):
        qs = department_filtered_queryset(table, organs, filters, with_request_status=True)
        add_status_counts(stats, request_status_counts(qs, stale_before=stale_before))
        active_organ_ids.update(qs.values_list("territorial_organ_id", flat=True).distinct())
        table_days, table_count = completion_totals_for_queryset(qs)
        completion_days_total += table_days
        completion_days_count += table_count
        candidate = latest_request_date_for_queryset(qs)
        if candidate and (latest_date is None or candidate > latest_date):
            latest_date = candidate

    avg_completion = completion_average_from_totals(completion_days_total, completion_days_count)
    return {
        "slug": department["slug"],
        "name": department["name"],
        "icon": department.get("icon") or department_icon(department["slug"]),
        "total": stats["total"],
        "in_work": stats["in_work"],
        "done": stats["done"],
        "rejected": stats["rejected"],
        "stale": stats["stale"],
        "active_organs": len(active_organ_ids),
        "avg_completion": avg_completion,
        "avg_completion_display": completion_display(avg_completion),
        "completion_days_total": completion_days_total,
        "completion_days_count": completion_days_count,
        "latest_date": latest_date,
        "latest_display": latest_date.strftime("%d.%m.%Y") if latest_date else "—",
        "detail_url": reverse("admin_department_detail", kwargs={"department_slug": department["slug"]}),
    }


def sort_department_rows(rows, view):
    default_key = lambda row: row["name"]
    if view == "best":
        return sorted(rows, key=lambda row: (row["avg_completion"] is None, row["avg_completion"] or 0, -row["done"], default_key(row)))
    if view == "stale":
        return sorted(rows, key=lambda row: (-row["stale"], -row["in_work"], default_key(row)))
    if view == "in_work":
        return sorted(rows, key=lambda row: (-row["in_work"], -row["total"], default_key(row)))
    return sorted(rows, key=default_key)


def visible_department_rows(rows, view):
    rows = [row for row in rows if row_matches_view(row, view)]
    return sort_department_rows(rows, view)


def build_departments_kpis(visible_rows):
    avg_completion = global_completion_average(visible_rows)
    busiest = max(visible_rows, key=lambda row: row["total"], default=None)
    most_stale = max(visible_rows, key=lambda row: row["stale"], default=None)
    return [
        {"label": "Всего отделов", "value": len(visible_rows), "hint": "в текущем списке", "icon": "bi-diagram-3"},
        {
            "label": "Самый загруженный",
            "value": busiest["total"] if busiest else "—",
            "hint": busiest["name"] if busiest and busiest["total"] else "нет заявок",
            "icon": "bi-bar-chart-line",
        },
        {
            "label": "Больше всего зависших",
            "value": most_stale["stale"] if most_stale else "—",
            "hint": most_stale["name"] if most_stale and most_stale["stale"] else "нет зависших",
            "icon": "bi-exclamation-triangle",
        },
        {
            "label": "Средний срок",
            "value": completion_display(avg_completion),
            "hint": "по исполненным заявкам",
            "icon": "bi-stopwatch",
        },
        {"label": "Без заявок", "value": sum(1 for row in visible_rows if row["total"] == 0), "hint": "по текущим фильтрам", "icon": "bi-inbox"},
    ]


def department_view_counts(all_rows):
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
        scalar_fields=("date_from", "date_to", "view", "q", "per_page"),
        list_fields=("request_status", "organ_ids"),
        flag_fields=("organ_filter_empty",),
    )


def active_filter_chips(filters, selected_organs_list, available_organs):
    chips = []
    if filters["period"]["date_from"] or filters["period"]["date_to"]:
        chips.append(f"Период: {filters['period']['label']}")
    if len(selected_organs_list) != len(available_organs):
        if len(selected_organs_list) == 1:
            chips.append(f"Орган: {selected_organs_list[0].name}")
        else:
            chips.append(f"Органы: {len(selected_organs_list)} из {len(available_organs)}")
    if filters.get("request_statuses"):
        chips.append(f"Статусы заявок: {filters['request_status_label']}")
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    if filters["view"] != "all":
        chips.append(f"Срез: {DEPARTMENT_VIEW_FILTERS[filters['view']]}")
    return chips


def build_filters(request):
    selected_status_values = selected_request_statuses(request)
    filters = {
        "period": date_period_from_request(request),
        "request_statuses": selected_status_values,
        "request_status": selected_status_values[0] if len(selected_status_values) == 1 else "all",
        "request_status_label": multiselect_label(selected_status_values, "Все статусы", REQUEST_STATUS_FILTERS),
        "view": selected_department_view(request),
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": selected_per_page(request),
        "stale_before": subtract_business_days_inclusive(timezone.localdate(), get_request_stale_workdays() + 1),
    }
    filters["per_page_label"] = f"{filters['per_page']} на странице"
    return filters


def build_departments_context(request):
    tables = list(request_tables())
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    departments = department_options(tables)
    filters = build_filters(request)
    visible_departments = filter_departments_by_search(departments, filters["query"])
    all_rows = [collect_department_stats(department, tables, organs, filters) for department in visible_departments]
    visible_rows = visible_department_rows(all_rows, filters["view"])
    counts = department_view_counts(all_rows)
    paginator = Paginator(visible_rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    selected_ids = {organ.pk for organ in organs}
    return {
        "active_tab": "departments",
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "filters": filters,
        "request_status_options": [(key, label) for key, label in REQUEST_STATUS_FILTERS.items() if key != "all"],
        "per_page_options": [50, 100],
        "departments_kpis": build_departments_kpis(visible_rows),
        "view_tabs": [
            {
                "key": key,
                "label": label,
                "count": counts.get(key, 0),
                "url": f"?{query_with(request, view=key)}",
                "active": filters["view"] == key,
            }
            for key, label in DEPARTMENT_VIEW_FILTERS.items()
        ],
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_departments_panel"),
        "pagination_fields": pagination_fields(request),
        "active_filter_chips": active_filter_chips(filters, organs, available_organs),
        "reset_url": reverse("admin_departments_panel"),
    }


def all_organ_stats_for_department(organs, department, tables, filters):
    """Build one stats row per organ in O(tables_for_department) queries instead of O(organs * tables).

    Same structural fix as admin_organs.collect_all_organ_stats: looping
    collect_organ_stats_for_department() once per organ meant e.g. 37 organs x
    1-2 department tables x 3 queries each on every department-detail page
    load. Grouping by territorial_organ inside one query per table gets the
    same numbers independent of how many organs are selected.
    """
    stale_before = filters["stale_before"]
    buckets = {organ.pk: {"stats": Counter(), "completion_days_total": 0, "completion_days_count": 0} for organ in organs}

    for table in tables_for_department(tables, department["slug"]):
        qs = table["model"].objects.filter(is_deleted=False, territorial_organ__in=organs)
        qs = apply_period(qs, filters["period"])
        qs = filter_by_request_statuses(qs, filters)

        counts_by_organ = request_status_counts_by_organ(qs, stale_before=stale_before)
        for organ_id, counts in counts_by_organ.items():
            bucket = buckets.get(organ_id)
            if bucket is not None:
                add_status_counts(bucket["stats"], counts)

        completion_by_organ = completion_totals_by_organ_for_queryset(qs)
        for organ_id, totals in completion_by_organ.items():
            bucket = buckets.get(organ_id)
            if bucket is not None:
                bucket["completion_days_total"] += totals["total"]
                bucket["completion_days_count"] += totals["count"]

    rows = {}
    for organ in organs:
        bucket = buckets[organ.pk]
        avg_completion = completion_average_from_totals(bucket["completion_days_total"], bucket["completion_days_count"])
        rows[organ.pk] = {
            "organ": organ,
            "total": bucket["stats"]["total"],
            "in_work": bucket["stats"]["in_work"],
            "done": bucket["stats"]["done"],
            "rejected": bucket["stats"]["rejected"],
            "stale": bucket["stats"]["stale"],
            "avg_completion": avg_completion,
            "avg_completion_display": completion_display(avg_completion),
            "organ_url": reverse("admin_organ_detail", kwargs={"pk": organ.pk}),
        }
    return rows


def collect_organ_stats_for_department(organ, department, tables, filters):
    return all_organ_stats_for_department([organ], department, tables, filters)[organ.pk]


def organ_rows_for_department(organs, department, tables, filters):
    stats_by_organ = all_organ_stats_for_department(organs, department, tables, filters)
    rows = [stats_by_organ[organ.pk] for organ in organs]
    rows = [row for row in rows if row["total"] > 0 or row["stale"] > 0 or row["in_work"] > 0]
    return sorted(rows, key=lambda row: (-row["total"], -row["in_work"], row["organ"].order_number, row["organ"].name))


def type_rows_for_department(department, tables, organs, filters):
    rows = []
    stale_before = filters["stale_before"]
    for table in tables_for_department(tables, department["slug"]):
        qs = department_filtered_queryset(table, organs, filters, with_request_status=True)
        counts = request_status_counts(qs, stale_before=stale_before)
        completion_days_total, completion_days_count = completion_totals_for_queryset(qs)
        avg_completion = completion_average_from_totals(completion_days_total, completion_days_count)
        rows.append(
            {
                "title": request_title(table, table["model"]()),
                "key": table["key"],
                **counts,
                "avg_completion": avg_completion,
                "avg_completion_display": completion_display(avg_completion),
            }
        )
    return rows


def latest_request_rows_for_department(department, tables, organs, filters, limit=15):
    rows = []
    departments = department_name_by_slug(department_options(tables))
    for table in tables_for_department(tables, department["slug"]):
        qs = department_filtered_queryset(table, organs, filters, with_request_status=True).order_by("-request_date", "-created_at", "-pk")
        for obj in qs[:limit]:
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


def build_department_detail_context(request, department_slug):
    tables = list(request_tables())
    departments = department_options(tables)
    department = next((item for item in departments if item["slug"] == department_slug), None)
    if not department:
        # Show a regular 404 for disabled or unknown department tabs.
        get_object_or_404(Department, slug=department_slug, is_active=True)
        raise Http404
    department_model = Department.objects.filter(slug=department_slug, is_active=True).first()
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    filters = build_filters(request)
    department_row = collect_department_stats(department, tables, organs, filters)
    selected_ids = {organ.pk for organ in organs}
    return {
        "active_tab": "departments",
        "department": department,
        "department_model": department_model,
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "filters": filters,
        "request_status_options": [(key, label) for key, label in REQUEST_STATUS_FILTERS.items() if key != "all"],
        "department_kpis": [
            {"label": "Всего заявок", "value": department_row["total"], "hint": filters["period"]["label"], "icon": "bi-inboxes"},
            {"label": "В работе", "value": department_row["in_work"], "hint": "текущие заявки", "icon": "bi-hourglass-split"},
            {"label": "Исполнено", "value": department_row["done"], "hint": "по текущим фильтрам", "icon": "bi-check2-circle"},
            {"label": "Зависшие", "value": department_row["stale"], "hint": f"более {get_request_stale_workdays()} рабочих дней", "icon": "bi-exclamation-triangle"},
            {"label": "Средний срок", "value": department_row["avg_completion_display"], "hint": "по исполненным заявкам", "icon": "bi-stopwatch"},
        ],
        "organ_rows": organ_rows_for_department(organs, department, tables, filters),
        "type_rows": type_rows_for_department(department, tables, organs, filters),
        "latest_requests": latest_request_rows_for_department(department, tables, organs, filters),
        "active_filter_chips": active_filter_chips(filters, organs, available_organs),
        "reset_url": reverse("admin_department_detail", kwargs={"department_slug": department_slug}),
        "back_url": reverse("admin_departments_panel"),
    }
