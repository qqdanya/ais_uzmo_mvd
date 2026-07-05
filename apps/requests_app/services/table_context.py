from django.core.paginator import Paginator

from apps.requests_app.models import ACTIVE_NEED_STATUS_CHOICES, CitsiziEquipment
from apps.requests_app.permissions import can_write

from .exports import display_fields
from .grouping import (
    attach_tmc_drilldown_querystrings,
    request_date_grouped_rows,
    request_group_mode,
    request_grouped_summary,
    request_organ_grouped_rows,
    request_status_stats,
    row_count,
    table_view_query_fields,
    tmc_date_grouped_rows,
    tmc_date_grouped_summary,
    tmc_grouped_rows,
    tmc_grouped_summary,
    tmc_organ_grouped_rows,
    tmc_organ_grouped_summary,
)
from .request_photos import attach_request_photo_counts
from .statuses import attach_status_history_flags
from .table_config import REQUEST_PHOTO_TABLES, REQUEST_TABLE_CONFIG, STATUS_HISTORY_TABLES
from .table_filters import (
    FIRE_EXTINGUISHER_EXPIRY_ORDER_CHOICES,
    FIRE_EXTINGUISHER_EXPIRY_STATE_CHOICES,
    STATE_SNAPSHOT_MODE_CHOICES,
    STATE_SNAPSHOT_TABLES,
    active_table_conditions,
    filtered_queryset,
    fire_extinguisher_active_conditions,
    fire_extinguisher_filtered_queryset,
    request_table_date_filter_defaults,
    request_table_date_filter_values,
    request_table_queryset,
    state_snapshot_mode,
    state_snapshot_queryset,
)

def _with_empty_choice(empty_label, choices):
    return [("", empty_label), *(choices or [])]


def _request_group_choices(table_key, is_multi_organ):
    choices = [{"value": "", "label": "По заявкам"}]
    if table_key == "tmc-requests":
        choices.append({"value": "products", "label": "По ТМЦ"})
    choices.append({"value": "dates", "label": "По дате"})
    choices.append({"value": "organs", "label": "По территориальному органу", "disabled": not is_multi_organ})
    return choices


def _group_select_value(group_mode):
    return "" if group_mode == "requests" else group_mode



def build_table_data_context(request, organ, table, table_key, selected_organs, organ_querystring=""):
    """Build the context for the main user-facing table partial."""
    is_multi_organ = len(selected_organs) > 1
    table_stats = {}
    table_filters = {}
    table_filter_defaults = {}

    qs = filtered_queryset(request, table, selected_organs)
    is_request_table = table_key in REQUEST_TABLE_CONFIG
    is_fire_extinguisher_table = table_key == "fire-extinguishers"
    is_state_snapshot_table = table_key in STATE_SNAPSHOT_TABLES
    current_state_mode = state_snapshot_mode(request, table_key)
    current_group_mode = request_group_mode(request, table_key, is_multi_organ) if is_request_table else "requests"

    if is_state_snapshot_table:
        qs = state_snapshot_queryset(request, table_key, qs)
    if is_fire_extinguisher_table:
        qs = fire_extinguisher_filtered_queryset(request, qs)

    is_request_grouped = current_group_mode in {"products", "organs", "dates"}
    is_tmc_grouped = table_key == "tmc-requests" and is_request_grouped
    is_tmc_product_grouped = table_key == "tmc-requests" and current_group_mode == "products"
    is_organ_grouped = current_group_mode == "organs"
    is_date_grouped = current_group_mode == "dates"

    if is_request_table:
        table_filter_defaults = request_table_date_filter_defaults(table_key, selected_organs)
        table_filters = request_table_date_filter_values(request, table_key, selected_organs)
        stats_qs = request_table_queryset(request, table_key, selected_organs)
        table_stats = request_status_stats(stats_qs)

    if is_tmc_product_grouped:
        page_qs = tmc_grouped_rows(qs)
    elif is_organ_grouped:
        page_qs = tmc_organ_grouped_rows(qs) if table_key == "tmc-requests" else request_organ_grouped_rows(qs)
    elif is_date_grouped:
        page_qs = tmc_date_grouped_rows(qs) if table_key == "tmc-requests" else request_date_grouped_rows(qs)
    else:
        page_qs = qs

    grouped_summary = {}
    grouped_count = row_count(page_qs)
    if is_tmc_product_grouped:
        grouped_summary = tmc_grouped_summary(qs, grouped_count)
    elif is_organ_grouped:
        grouped_summary = tmc_organ_grouped_summary(qs, grouped_count) if table_key == "tmc-requests" else request_grouped_summary(qs, organ_count=grouped_count)
    elif is_date_grouped:
        grouped_summary = tmc_date_grouped_summary(qs, grouped_count) if table_key == "tmc-requests" else request_grouped_summary(qs, date_count=grouped_count)

    paginator = Paginator(page_qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    if table_key in REQUEST_PHOTO_TABLES and not is_request_grouped:
        attach_request_photo_counts(page.object_list, table["model"], selected_organs)
    if table_key in STATUS_HISTORY_TABLES and not is_request_grouped:
        attach_status_history_flags(page.object_list, table["model"])

    querystring = request.GET.copy()
    querystring.pop("page", None)
    list_querystring = querystring.copy()
    list_querystring.pop("group", None)
    grouped_querystring = querystring.copy()
    grouped_querystring["group"] = "products"
    organ_grouped_querystring = querystring.copy()
    organ_grouped_querystring["group"] = "organs"

    if is_tmc_product_grouped:
        page.object_list = attach_tmc_drilldown_querystrings(list(page.object_list), list_querystring)

    active_conditions = (
        fire_extinguisher_active_conditions(request, selected_organs)
        if is_fire_extinguisher_table
        else active_table_conditions(request, table_key, selected_organs, current_group_mode)
    )
    if is_state_snapshot_table and current_state_mode == "history":
        active_conditions.append("режим: История записей")

    writable_organ_ids = [
        selected_organ.pk
        for selected_organ in selected_organs
        if can_write(request.user, selected_organ, table["department"])
    ]

    return {
        "organ": organ,
        "table": table,
        "fields": display_fields(table),
        "page": page,
        "table_page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "can_add": can_write(request.user, organ, table["department"]) and not is_multi_organ,
        "writable_organ_ids": writable_organ_ids,
        "table_querystring": querystring.urlencode(),
        "list_querystring": list_querystring.urlencode(),
        "grouped_querystring": grouped_querystring.urlencode(),
        "organ_grouped_querystring": organ_grouped_querystring.urlencode(),
        "table_view_query_fields": table_view_query_fields(querystring),
        "organ_querystring": organ_querystring,
        "status_choices": ACTIVE_NEED_STATUS_CHOICES,
        "status_filter_choices": _with_empty_choice("Все статусы", ACTIVE_NEED_STATUS_CHOICES),
        "table_stats": table_stats,
        "table_filters": table_filters,
        "table_filter_defaults": table_filter_defaults,
        "active_conditions": active_conditions,
        "grouped_summary": grouped_summary,
        "tmc_summary": grouped_summary,
        "is_request_table": is_request_table,
        "is_fire_extinguisher_table": is_fire_extinguisher_table,
        "is_state_snapshot_table": is_state_snapshot_table,
        "state_snapshot_mode": current_state_mode,
        "state_snapshot_mode_choices": STATE_SNAPSHOT_MODE_CHOICES,
        "is_request_grouped": is_request_grouped,
        "is_tmc_grouped": is_tmc_grouped,
        "is_tmc_product_grouped": is_tmc_product_grouped,
        "is_tmc_organ_grouped": table_key == "tmc-requests" and is_organ_grouped,
        "is_tmc_date_grouped": table_key == "tmc-requests" and is_date_grouped,
        "is_organ_grouped": is_organ_grouped,
        "is_date_grouped": is_date_grouped,
        "tmc_group_mode": current_group_mode,
        "group_mode": current_group_mode,
        "group_select_value": _group_select_value(current_group_mode),
        "request_group_choices": _request_group_choices(table_key, is_multi_organ),
        "record_label": "позиций" if is_tmc_product_grouped else "органов" if is_organ_grouped else "дней" if is_date_grouped else "записей",
        "has_status_history": table_key in STATUS_HISTORY_TABLES,
        "search_placeholder": "Поиск по заявке и ТМЦ" if table_key == "tmc-requests" else "Поиск по заявке и описанию",
        "equipment_type_choices": CitsiziEquipment._meta.get_field("equipment_type").choices,
        "equipment_type_filter_choices": _with_empty_choice("Все типы техники", CitsiziEquipment._meta.get_field("equipment_type").choices),
        "fire_extinguisher_expiry_state_choices": FIRE_EXTINGUISHER_EXPIRY_STATE_CHOICES,
        "fire_extinguisher_expiry_order_choices": FIRE_EXTINGUISHER_EXPIRY_ORDER_CHOICES,
        "selected_organs": selected_organs,
        "is_multi_organ": is_multi_organ,
    }
