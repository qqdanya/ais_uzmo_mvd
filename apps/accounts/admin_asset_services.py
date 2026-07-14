from collections import Counter
from datetime import timedelta

from django.db.models import OuterRef, Subquery
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_common import filter_model_objects_by_search, selected_values
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
    "fire-alarm": "Состояние объектов, подлежащих оборудованию пожарной сигнализацией",
    "security-alarm": "Состояние объектов, подлежащих оборудованию охранной сигнализацией",
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


def workspace_table_url(organ_id, table_key):
    """Deep link into the dashboard work screen at a given organ and table.

    record_update ("/organs/.../edit/") is an htmx-only endpoint that returns
    a bare form fragment for the dashboard's modal - linking a browser
    straight to it renders an unstyled page. The dashboard restores
    ?organ/?department/?table from the URL on load (organ_navigation.js), so
    this is the address that actually opens the record's table in the
    workspace.
    """
    table = TABLE_BY_KEY[table_key]
    return f"{reverse('dashboard')}?organ={organ_id}&department={table['department']}&table={table_key}"


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
                "hint": ASSET_CATEGORY_HINTS.get(key, "Текущее состояние по последней записи"),
                "detail_url": reverse("admin_asset_category_detail", kwargs={"category_key": key}),
            }
        )
    return categories


def selected_asset_categories(request, categories):
    return selected_values(request, "category", [item["key"] for item in categories])


def selected_asset_statuses(request):
    return selected_values(request, "asset_status", ASSET_STATUS_FILTERS.keys())


def filter_organs_by_search(organs, query):
    return filter_model_objects_by_search(
        organs,
        query,
        text_fields=("name", "description"),
        numeric_fields=("order_number",),
    )


def visible_categories(categories, selected_categories):
    if not selected_categories:
        return categories
    return [item for item in categories if item["key"] in selected_categories]


def latest_objects_by_organ(category, organs):
    organ_ids = [organ.pk for organ in organs]
    if not organ_ids:
        return {}
    model = category["model"]
    # A correlated subquery finds each organ's latest row by pk alone (cheap,
    # index-friendly), so the DB never has to hydrate the full submission
    # history into Python just to keep the single newest row per organ.
    latest_pk_subquery = (
        model.objects
        .filter(is_deleted=False, territorial_organ_id=OuterRef("pk"))
        .order_by("-state_date", "-created_at", "-pk")
        .values("pk")[:1]
    )
    latest_pks = (
        TerritorialOrgan.objects.filter(pk__in=organ_ids)
        .annotate(latest_asset_pk=Subquery(latest_pk_subquery))
        .values_list("latest_asset_pk", flat=True)
    )
    objects = model.objects.select_related("territorial_organ").filter(pk__in=[pk for pk in latest_pks if pk is not None])
    return {obj.territorial_organ_id: obj for obj in objects}


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
        return make_status("no_data", "данные не внесены", category=category, organ=organ)
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
        return make_status("no_data", "данные не внесены", category=category, organ=organ)
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
        return make_status("no_data", "данные не внесены", category=category, organ=organ)
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
        return make_status("no_data", "данные не внесены", category=category, organ=organ)
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
                cell["edit_url"] = workspace_table_url(organ.pk, category["key"])
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
        {"label": "Категории", "value": len(categories), "hint": "учитываются в разделе", "icon": "bi-grid-3x3-gap"},
        {"label": "Данные представлены полностью", "value": complete_actual, "hint": f"из {total_organs} органов", "icon": "bi-check2-circle"},
        {"label": "Требует внимания", "value": attention_organs, "hint": "территориальные органы", "icon": "bi-exclamation-triangle"},
        {"label": "Есть пробелы в данных", "value": no_data_organs, "hint": "нет записи в категории", "icon": "bi-database-x"},
        {"label": "Давно не обновлялось", "value": stale_organs, "hint": f"старше {get_asset_stale_days()} дней", "icon": "bi-clock-history"},
    ]


def build_category_charts(category_summaries):
    items = [
        {
            "label": item["title"],
            "value": item["issue_score"],
            "hint": f"требует внимания: {item['attention_count']}, нет данных: {item['no_data_count']}",
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
                "hint": f"проблем: {row['danger']}, требует внимания: {row['warning'] + row['stale']}, нет данных: {row['no_data']}",
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
