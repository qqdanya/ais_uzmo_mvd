from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from apps.directory.models import TerritorialOrgan
from apps.requests_app.registry import get_table_or_404

from .admin_asset_services import (
    ASSET_STATUS_FILTERS,
    asset_categories,
    asset_status_counts,
    build_asset_matrix,
    build_assets_kpis,
    build_category_charts,
    build_top_problem_organs,
    category_summary,
    date_display,
    filter_asset_rows,
    filter_organs_by_search,
    selected_asset_categories,
    selected_asset_statuses,
    sort_asset_rows,
    visible_categories,
)
from .admin_common import (
    DEFAULT_PER_PAGE,
    build_pagination_fields,
    field_label,
    field_value,
    multiselect_label,
    query_with,
)
from .admin_summary import available_organs_for_user, selected_organs
from .admin_thresholds import get_asset_stale_days


def asset_pagination_fields(request):
    return build_pagination_fields(
        request,
        scalar_fields=("q",),
        list_fields=("category", "asset_status", "organ_ids"),
        flag_fields=("organ_filter_empty",),
    )


def category_pagination_fields(request):
    return build_pagination_fields(
        request,
        scalar_fields=("q",),
        list_fields=("asset_status", "organ_ids"),
        flag_fields=("organ_filter_empty",),
    )


def build_asset_filters(request, categories):
    filters = {
        "categories": selected_asset_categories(request, categories),
        "asset_statuses": selected_asset_statuses(request),
        "category": "",
        "asset_status": "all",
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": DEFAULT_PER_PAGE,
    }
    filters["category"] = filters["categories"][0] if len(filters["categories"]) == 1 else ""
    filters["asset_status"] = filters["asset_statuses"][0] if len(filters["asset_statuses"]) == 1 else "all"
    filters["category_label"] = multiselect_label(filters["categories"], "Все категории", {item["key"]: item["title"] for item in categories})
    filters["asset_status_label"] = multiselect_label(filters["asset_statuses"], "Все состояния", ASSET_STATUS_FILTERS)
    return filters


def build_asset_category_filters(request):
    filters = {
        "asset_statuses": selected_asset_statuses(request),
        "asset_status": "all",
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": DEFAULT_PER_PAGE,
    }
    filters["asset_status"] = filters["asset_statuses"][0] if len(filters["asset_statuses"]) == 1 else "all"
    filters["asset_status_label"] = multiselect_label(filters["asset_statuses"], "Все состояния", ASSET_STATUS_FILTERS)
    return filters


def build_asset_status_tabs(request, filters, counts):
    return [
        {
            "key": key,
            "label": label,
            "count": counts.get(key, 0),
            "url": f"?{query_with(request, asset_status=key)}",
            "active": (not filters["asset_statuses"] and key == "all") or filters["asset_statuses"] == [key],
        }
        for key, label in ASSET_STATUS_FILTERS.items()
    ]


def active_filter_chips(filters, selected_organs_list, available_organs, categories):
    chips = []
    if len(selected_organs_list) != len(available_organs):
        if len(selected_organs_list) == 1:
            chips.append(f"Орган: {selected_organs_list[0].name}")
        else:
            chips.append(f"Органы: {len(selected_organs_list)} из {len(available_organs)}")
    if filters.get("categories"):
        chips.append(f"Категории: {filters['category_label']}")
    if filters.get("asset_statuses"):
        chips.append(f"Состояния: {filters['asset_status_label']}")
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    return chips


def build_assets_context(request):
    categories = asset_categories()
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    filters = build_asset_filters(request, categories)
    organs_for_matrix = filter_organs_by_search(organs, filters["query"])
    matrix_categories = visible_categories(categories, filters["categories"])
    all_rows = build_asset_matrix(organs_for_matrix, matrix_categories)
    visible_rows = sort_asset_rows(filter_asset_rows(all_rows, filters["asset_statuses"]))
    category_summaries = [category_summary(category, all_rows) for category in matrix_categories]
    counts = asset_status_counts(all_rows)
    paginator = Paginator(visible_rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    selected_ids = {organ.pk for organ in organs}
    return {
        "active_tab": "assets",
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "categories": categories,
        "matrix_categories": matrix_categories,
        "filters": filters,
        "asset_status_options": [(key, label) for key, label in ASSET_STATUS_FILTERS.items() if key != "all"],
        "asset_kpis": build_assets_kpis(all_rows, matrix_categories),
        "category_summaries": category_summaries,
        "category_chart": build_category_charts(category_summaries),
        "top_problem_organs": build_top_problem_organs(all_rows),
        "status_tabs": build_asset_status_tabs(request, filters, counts),
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_assets_panel"),
        "pagination_fields": asset_pagination_fields(request),
        "active_filter_chips": active_filter_chips(filters, organs, available_organs, categories),
        "reset_url": reverse("admin_assets_panel"),
        "stale_days": get_asset_stale_days(),
    }


def get_asset_category(category_key):
    category = next((item for item in asset_categories() if item["key"] == category_key), None)
    if not category:
        raise Http404
    return category


def category_current_rows(category, organs, status_filter="all", query=""):
    filtered_organs = filter_organs_by_search(organs, query)
    rows = build_asset_matrix(filtered_organs, [category])
    return sort_asset_rows(filter_asset_rows(rows, status_filter))


def category_history(category, organs, limit=12):
    organ_ids = [organ.pk for organ in organs]
    if not organ_ids:
        return []
    rows = []
    qs = (
        category["model"].objects.select_related("territorial_organ", "created_by", "updated_by")
        .filter(is_deleted=False, territorial_organ_id__in=organ_ids)
        .order_by("-state_date", "-created_at", "-pk")[:limit]
    )
    for obj in qs:
        rows.append(
            {
                "object": obj,
                "organ": obj.territorial_organ,
                "date_display": date_display(obj.state_date),
                "fields": field_rows(category, obj),
                "edit_url": reverse("record_update", kwargs={"organ_id": obj.territorial_organ_id, "table_key": category["key"], "pk": obj.pk}),
            }
        )
    return rows


def field_rows(category, obj):
    rows = []
    table = get_table_or_404(category["key"])
    for name in category.get("fields", []):
        rows.append({"label": field_label(table, name), "value": field_value(obj, name)})
    return rows


def build_asset_category_detail_context(request, category_key):
    category = get_asset_category(category_key)
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    filters = build_asset_category_filters(request)
    rows_all = category_current_rows(category, organs, "all", filters["query"])
    rows = filter_asset_rows(rows_all, filters["asset_statuses"])
    counts = asset_status_counts(rows_all)
    paginator = Paginator(rows, filters["per_page"])
    page = paginator.get_page(request.GET.get("page"))
    selected_ids = {organ.pk for organ in organs}
    return {
        "active_tab": "assets",
        "category": category,
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "filters": filters,
        "asset_status_options": [(key, label) for key, label in ASSET_STATUS_FILTERS.items() if key != "all"],
        "summary": category_summary(category, rows_all),
        "status_tabs": build_asset_status_tabs(request, filters, counts),
        "page": page,
        "page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "querystring": query_with(request),
        "pagination_url": reverse("admin_asset_category_detail", kwargs={"category_key": category_key}),
        "pagination_fields": category_pagination_fields(request),
        "history_rows": category_history(category, organs),
        "reset_url": reverse("admin_asset_category_detail", kwargs={"category_key": category_key}),
        "back_url": reverse("admin_assets_panel"),
        "stale_days": get_asset_stale_days(),
    }



def build_asset_organ_summary_context(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    available_organs = available_organs_for_user(request.user)
    if organ not in list(available_organs):
        raise Http404
    categories = asset_categories()
    rows = build_asset_matrix([organ], categories)
    row = rows[0] if rows else None
    history = []
    for category in categories:
        qs = category["model"].objects.filter(is_deleted=False, territorial_organ=organ).order_by("-state_date", "-created_at", "-pk")[:5]
        history.append({"category": category, "items": [{"object": obj, "date_display": date_display(obj.state_date), "fields": field_rows(category, obj)} for obj in qs]})
    return {
        "active_tab": "assets",
        "organ": organ,
        "row": row,
        "categories": categories,
        "history_groups": history,
        "back_url": reverse("admin_assets_panel"),
        "stale_days": get_asset_stale_days(),
    }


ASSET_ORGAN_DETAIL_HISTORY_LIMIT = 50


def build_asset_organ_detail_context(request, category_key, organ_id):
    category = get_asset_category(category_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    available_organs = available_organs_for_user(request.user)
    if organ not in list(available_organs):
        raise Http404
    rows = build_asset_matrix([organ], [category])
    cell = rows[0]["cells"][0] if rows else None
    history = []
    qs = category["model"].objects.filter(is_deleted=False, territorial_organ=organ).order_by("-state_date", "-created_at", "-pk")[:ASSET_ORGAN_DETAIL_HISTORY_LIMIT]
    for obj in qs:
        history.append(
            {
                "object": obj,
                "date_display": date_display(obj.state_date),
                "fields": field_rows(category, obj),
                "edit_url": reverse("record_update", kwargs={"organ_id": organ.pk, "table_key": category["key"], "pk": obj.pk}),
            }
        )
    return {
        "active_tab": "assets",
        "category": category,
        "organ": organ,
        "cell": cell,
        "history_rows": history,
        "back_url": reverse("admin_asset_category_detail", kwargs={"category_key": category_key}),
        "stale_days": get_asset_stale_days(),
    }
