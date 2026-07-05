from collections import Counter
from datetime import timedelta

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.registry import TABLE_BY_KEY, get_table_or_404

from .admin_common import (
    build_pagination_fields,
    field_label,
    field_value,
    multiselect_label,
    query_with,
    selected_per_page,
    selected_values,
)
from .admin_summary import available_organs_for_user, selected_organs
from .admin_thresholds import get_asset_stale_days


ASSET_CATEGORY_KEYS = [
    "fire-extinguishers",
    "fire-alarm",
    "security-alarm",
    "service-housing",
]

ASSET_CATEGORY_ICONS = {
    "fire-extinguishers": "bi-fire",
    "fire-alarm": "bi-broadcast-pin",
    "security-alarm": "bi-shield-check",
    "service-housing": "bi-house-door",
}

ASSET_CATEGORY_HINTS = {
    "fire-extinguishers": "Последняя запись по огнетушителям в каждом территориальном органе",
    "fire-alarm": "Актуальное состояние объектов, подлежащих оборудованию пожарной сигнализацией",
    "security-alarm": "Актуальное состояние объектов, подлежащих оборудованию охранной сигнализацией",
    "service-housing": "Последняя запись по служебному жилью по линии УОТО",
}

ASSET_STATUS_FILTERS = {
    "all": "Все",
    "attention": "Требует внимания",
    "danger": "Проблемные",
    "stale": "Давно не обновлялось",
    "no_data": "Нет данных",
    "ok": "Норма",
}

ASSET_STATUS_LABELS = {
    "ok": "Норма",
    "warning": "Требует внимания",
    "danger": "Проблема",
    "stale": "Устарело",
    "no_data": "Нет данных",
}

ASSET_STATUS_CLASSES = {
    "ok": "is-ok",
    "warning": "is-warning",
    "danger": "is-danger",
    "stale": "is-stale",
    "no_data": "is-empty",
}


def date_display(value):
    return value.strftime("%d.%m.%Y") if value else "—"


def age_days(value):
    if not value:
        return None
    return max((timezone.localdate() - value).days, 0)


def is_stale(value):
    days = age_days(value)
    return days is not None and days > get_asset_stale_days()


def department_names():
    return {item.slug: item.name for item in Department.objects.filter(is_active=True)}


def asset_categories():
    departments = department_names()
    categories = []
    for key in ASSET_CATEGORY_KEYS:
        table = TABLE_BY_KEY.get(key)
        if not table:
            continue
        categories.append(
            {
                "key": key,
                "title": table["title"],
                "model": table["model"],
                "department": table["department"],
                "department_name": departments.get(table["department"], table["department"]),
                "fields": table.get("fields", []),
                "icon": ASSET_CATEGORY_ICONS.get(key, "bi-box-seam"),
                "hint": ASSET_CATEGORY_HINTS.get(key, "Актуальное состояние по последней записи"),
                "detail_url": reverse("admin_asset_category_detail", kwargs={"category_key": key}),
            }
        )
    return categories


def selected_asset_categories(request, categories):
    return selected_values(request, "category", [item["key"] for item in categories])


def selected_asset_statuses(request):
    return selected_values(request, "asset_status", ASSET_STATUS_FILTERS.keys())


def filter_organs_by_search(organs, query):
    query = (query or "").strip().casefold()
    if not query:
        return list(organs)
    return [
        organ
        for organ in organs
        if query in organ.name.casefold()
        or query in str(organ.order_number).casefold()
        or query in (organ.description or "").casefold()
    ]


def visible_categories(categories, selected_categories):
    if not selected_categories:
        return categories
    return [item for item in categories if item["key"] in selected_categories]


def latest_objects_by_organ(category, organs):
    organ_ids = [organ.pk for organ in organs]
    latest = {}
    if not organ_ids:
        return latest
    qs = (
        category["model"].objects.select_related("territorial_organ")
        .filter(is_deleted=False, territorial_organ_id__in=organ_ids)
        .order_by("territorial_organ_id", "-state_date", "-created_at", "-pk")
    )
    for obj in qs:
        latest.setdefault(obj.territorial_organ_id, obj)
    return latest


def make_status(status, message, *, state_date=None, metrics=None, object_=None, category=None, organ=None, reasons=None):
    days = age_days(state_date)
    return {
        "status": status,
        "label": ASSET_STATUS_LABELS.get(status, status),
        "class": ASSET_STATUS_CLASSES.get(status, ""),
        "message": message,
        "state_date": state_date,
        "state_date_display": date_display(state_date),
        "age_days": days,
        "metrics": metrics or [],
        "object": object_,
        "category": category,
        "organ": organ,
        "reasons": reasons or [],
    }


def with_stale_status(base_status, messages, state_date):
    if is_stale(state_date):
        messages.append(f"данные старше {get_asset_stale_days()} дней")
        if base_status == "ok":
            return "stale"
        if base_status == "warning":
            return "warning"
        return base_status
    return base_status


def evaluate_fire_extinguishers(obj, category, organ):
    if not obj:
        return make_status("no_data", "нет актуальной записи", category=category, organ=organ)
    danger = []
    warning = []
    if obj.available_count < obj.required_count:
        danger.append(f"недостаток: {obj.required_count - obj.available_count}")
    if obj.expiry_date < timezone.localdate():
        danger.append("срок эксплуатации истёк")
    elif obj.expiry_date <= timezone.localdate() + timedelta(days=30):
        warning.append("срок скоро истекает")
    if obj.writeoff_count:
        warning.append(f"к списанию: {obj.writeoff_count}")
    status = "danger" if danger else "warning" if warning else "ok"
    status = with_stale_status(status, warning, obj.state_date)
    reasons = danger + warning
    message = "; ".join(reasons) if reasons else "показатели в норме"
    return make_status(
        status,
        message,
        state_date=obj.state_date,
        metrics=[
            f"Положено: {obj.required_count}",
            f"Наличие: {obj.available_count}",
            f"Срок: {date_display(obj.expiry_date)}",
            f"К списанию: {obj.writeoff_count}",
        ],
        object_=obj,
        category=category,
        organ=organ,
        reasons=reasons,
    )


def evaluate_alarm(obj, category, organ, short_name):
    if not obj:
        return make_status("no_data", "нет актуальной записи", category=category, organ=organ)
    danger = []
    warning = []
    if obj.equipped_objects < obj.required_objects:
        danger.append(f"не оборудовано: {obj.required_objects - obj.equipped_objects}")
    if obj.broken_objects:
        danger.append(f"неисправно: {obj.broken_objects}")
    status = "danger" if danger else "ok"
    status = with_stale_status(status, warning, obj.state_date)
    reasons = danger + warning
    message = "; ".join(reasons) if reasons else "показатели в норме"
    return make_status(
        status,
        message,
        state_date=obj.state_date,
        metrics=[
            f"Подлежит оборудованию: {obj.required_objects}",
            f"Оборудовано {short_name}: {obj.equipped_objects}",
            f"Неисправно: {obj.broken_objects}",
        ],
        object_=obj,
        category=category,
        organ=organ,
        reasons=reasons,
    )


def evaluate_service_housing(obj, category, organ):
    if not obj:
        return make_status("no_data", "нет актуальной записи", category=category, organ=organ)
    warning = []
    if obj.total_count == 0:
        warning.append("служебное жильё отсутствует")
    if obj.ready_to_move == 0 and obj.total_count > 0:
        warning.append("нет жилья, готового к заселению")
    untracked = obj.total_count - obj.used_by_staff - obj.ready_to_move
    if untracked > 0:
        warning.append(f"не распределено/не готово: {untracked}")
    status = "warning" if warning else "ok"
    status = with_stale_status(status, warning, obj.state_date)
    reasons = warning
    message = "; ".join(reasons) if reasons else "показатели в норме"
    return make_status(
        status,
        message,
        state_date=obj.state_date,
        metrics=[
            f"Всего: {obj.total_count}",
            f"Используется: {obj.used_by_staff}",
            f"Готово к заселению: {obj.ready_to_move}",
        ],
        object_=obj,
        category=category,
        organ=organ,
        reasons=reasons,
    )


def evaluate_asset(category, obj, organ):
    if category["key"] == "fire-extinguishers":
        return evaluate_fire_extinguishers(obj, category, organ)
    if category["key"] == "fire-alarm":
        return evaluate_alarm(obj, category, organ, "ПС")
    if category["key"] == "security-alarm":
        return evaluate_alarm(obj, category, organ, "ОС")
    if category["key"] == "service-housing":
        return evaluate_service_housing(obj, category, organ)
    if not obj:
        return make_status("no_data", "нет актуальной записи", category=category, organ=organ)
    return make_status("ok", "показатели в норме", state_date=getattr(obj, "state_date", None), object_=obj, category=category, organ=organ)


def cell_matches_status(cell, status_filter):
    if status_filter == "all":
        return True
    if status_filter == "attention":
        return cell["status"] in {"warning", "danger", "stale"}
    if status_filter == "danger":
        return cell["status"] == "danger"
    if status_filter == "stale":
        return cell["status"] == "stale" or (cell.get("age_days") is not None and cell["age_days"] > get_asset_stale_days())
    if status_filter == "no_data":
        return cell["status"] == "no_data"
    if status_filter == "ok":
        return cell["status"] == "ok"
    return True


def normalized_asset_status_filters(status_filter):
    values = status_filter if isinstance(status_filter, (list, tuple, set)) else [status_filter]
    return [item for item in values if item and item != "all"]


def row_matches_asset_statuses(row, status_filter):
    status_filters = normalized_asset_status_filters(status_filter)
    if not status_filters:
        return True
    return any(cell_matches_status(cell, status_filter) for status_filter in status_filters for cell in row["cells"])


def filter_asset_rows(rows, status_filter):
    return [row for row in rows if row_matches_asset_statuses(row, status_filter)]


def sort_asset_rows(rows):
    return sorted(rows, key=lambda row: (-row["issue_score"], -row["danger"], -row["attention"], row["organ"].order_number, row["organ"].name))


def issue_weight(cell):
    if cell["status"] == "danger":
        return 3
    if cell["status"] in {"warning", "stale"}:
        return 2
    if cell["status"] == "no_data":
        return 1
    return 0


def build_asset_matrix(organs, categories):
    latest_by_category = {category["key"]: latest_objects_by_organ(category, organs) for category in categories}
    rows = []
    for organ in organs:
        cells = []
        latest_date = None
        for category in categories:
            obj = latest_by_category[category["key"]].get(organ.pk)
            cell = evaluate_asset(category, obj, organ)
            if obj:
                cell["history_url"] = reverse("admin_asset_organ_detail", kwargs={"category_key": category["key"], "organ_id": organ.pk})
                cell["edit_url"] = reverse("record_update", kwargs={"organ_id": organ.pk, "table_key": category["key"], "pk": obj.pk})
            else:
                cell["history_url"] = reverse("admin_asset_organ_detail", kwargs={"category_key": category["key"], "organ_id": organ.pk})
                cell["edit_url"] = None
            cells.append(cell)
            if cell["state_date"] and (latest_date is None or cell["state_date"] > latest_date):
                latest_date = cell["state_date"]
        counters = Counter(cell["status"] for cell in cells)
        stale_count = sum(1 for cell in cells if cell_matches_status(cell, "stale"))
        attention_count = counters["warning"] + counters["danger"] + counters["stale"]
        issue_score = sum(issue_weight(cell) for cell in cells)
        rows.append(
            {
                "organ": organ,
                "cells": cells,
                "ok": counters["ok"],
                "attention": attention_count,
                "danger": counters["danger"],
                "warning": counters["warning"],
                "stale": stale_count,
                "no_data": counters["no_data"],
                "issue_score": issue_score,
                "latest_date": latest_date,
                "latest_display": date_display(latest_date),
                "detail_url": reverse("admin_asset_organ_summary", kwargs={"organ_id": organ.pk}),
            }
        )
    return rows


def category_summary(category, rows):
    cells = [cell for row in rows for cell in row["cells"] if cell["category"]["key"] == category["key"]]
    latest_date = None
    for cell in cells:
        if cell["state_date"] and (latest_date is None or cell["state_date"] > latest_date):
            latest_date = cell["state_date"]
    data_count = sum(1 for cell in cells if cell["status"] != "no_data")
    no_data_count = sum(1 for cell in cells if cell["status"] == "no_data")
    attention_count = sum(1 for cell in cells if cell["status"] in {"warning", "danger", "stale"})
    danger_count = sum(1 for cell in cells if cell["status"] == "danger")
    stale_count = sum(1 for cell in cells if cell_matches_status(cell, "stale"))
    issue_score = attention_count + no_data_count
    return {
        **category,
        "data_count": data_count,
        "no_data_count": no_data_count,
        "attention_count": attention_count,
        "danger_count": danger_count,
        "stale_count": stale_count,
        "issue_score": issue_score,
        "latest_date": latest_date,
        "latest_display": date_display(latest_date),
        "data_label": f"{data_count} из {len(cells)}" if cells else "—",
    }


def add_bar_widths(items, value_key="value"):
    max_value = max((item.get(value_key) or 0 for item in items), default=0)
    for item in items:
        value = item.get(value_key) or 0
        item["bar_width"] = int(round((value / max_value) * 100)) if max_value else 0
    return items


def build_assets_kpis(rows, categories):
    total_organs = len(rows)
    complete_actual = sum(1 for row in rows if row["no_data"] == 0 and row["stale"] == 0)
    attention_organs = sum(1 for row in rows if row["attention"] > 0 or row["danger"] > 0)
    no_data_organs = sum(1 for row in rows if row["no_data"] > 0)
    stale_organs = sum(1 for row in rows if row["stale"] > 0)
    return [
        {"label": "Категорий на контроле", "value": len(categories), "hint": "актуальные срезы", "icon": "bi-grid-3x3-gap"},
        {"label": "Полный актуальный срез", "value": complete_actual, "hint": f"из {total_organs} органов", "icon": "bi-check2-circle"},
        {"label": "Требует внимания", "value": attention_organs, "hint": "органы с сигналами", "icon": "bi-exclamation-triangle"},
        {"label": "Есть пробелы в данных", "value": no_data_organs, "hint": "нет записи в категории", "icon": "bi-database-x"},
        {"label": "Давно не обновлялось", "value": stale_organs, "hint": f"старше {get_asset_stale_days()} дней", "icon": "bi-clock-history"},
    ]


def build_category_charts(category_summaries):
    items = [
        {
            "label": item["title"],
            "value": item["issue_score"],
            "hint": f"внимание: {item['attention_count']}, нет данных: {item['no_data_count']}",
            "url": item["detail_url"],
        }
        for item in category_summaries
    ]
    items.sort(key=lambda item: (-item["value"], item["label"]))
    return add_bar_widths(items)


def build_top_problem_organs(rows, limit=10):
    items = []
    for row in rows:
        value = row["issue_score"]
        if value <= 0:
            continue
        items.append(
            {
                "label": row["organ"].name,
                "value": value,
                "hint": f"проблем: {row['danger']}, внимание: {row['warning'] + row['stale']}, нет данных: {row['no_data']}",
                "url": row["detail_url"],
            }
        )
    items.sort(key=lambda item: (-item["value"], item["label"]))
    return add_bar_widths(items[:limit])


def asset_status_counts(rows):
    return {
        "all": len(rows),
        "attention": sum(1 for row in rows if row["attention"] > 0),
        "danger": sum(1 for row in rows if row["danger"] > 0),
        "stale": sum(1 for row in rows if row["stale"] > 0),
        "no_data": sum(1 for row in rows if row["no_data"] > 0),
        "ok": sum(1 for row in rows if row["issue_score"] == 0),
    }


def asset_pagination_fields(request):
    return build_pagination_fields(
        request,
        scalar_fields=("q", "per_page"),
        list_fields=("category", "asset_status", "organ_ids"),
        flag_fields=("organ_filter_empty",),
    )


def category_pagination_fields(request):
    return build_pagination_fields(
        request,
        scalar_fields=("q", "per_page"),
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
        "per_page": selected_per_page(request),
    }
    filters["category"] = filters["categories"][0] if len(filters["categories"]) == 1 else ""
    filters["asset_status"] = filters["asset_statuses"][0] if len(filters["asset_statuses"]) == 1 else "all"
    filters["category_label"] = multiselect_label(filters["categories"], "Все категории", {item["key"]: item["title"] for item in categories})
    filters["asset_status_label"] = multiselect_label(filters["asset_statuses"], "Все состояния", ASSET_STATUS_FILTERS)
    filters["per_page_label"] = f"{filters['per_page']} на странице"
    return filters


def build_asset_category_filters(request):
    filters = {
        "asset_statuses": selected_asset_statuses(request),
        "asset_status": "all",
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": selected_per_page(request),
    }
    filters["asset_status"] = filters["asset_statuses"][0] if len(filters["asset_statuses"]) == 1 else "all"
    filters["asset_status_label"] = multiselect_label(filters["asset_statuses"], "Все состояния", ASSET_STATUS_FILTERS)
    filters["per_page_label"] = f"{filters['per_page']} на странице"
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
        "per_page_options": [50, 100],
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
        "per_page_options": [50, 100],
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


def build_asset_organ_detail_context(request, category_key, organ_id):
    category = get_asset_category(category_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    available_organs = available_organs_for_user(request.user)
    if organ not in list(available_organs):
        raise Http404
    rows = build_asset_matrix([organ], [category])
    cell = rows[0]["cells"][0] if rows else None
    history = []
    qs = category["model"].objects.filter(is_deleted=False, territorial_organ=organ).order_by("-state_date", "-created_at", "-pk")
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
