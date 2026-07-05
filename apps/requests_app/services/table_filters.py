"""Filtering helpers for dashboard request and state tables."""

from datetime import timedelta

from django.db.models import Min, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.requests_app.models import ACTIVE_NEED_STATUS_CHOICES, CitsiziEquipment
from apps.search_utils import apply_text_search, build_text_search_q, search_query_variants
from apps.requests_app.services.table_config import REQUEST_TABLE_CONFIG


def filtered_queryset(request, table, organs):
    qs = table["model"].objects.select_related("territorial_organ", "created_by", "updated_by").filter(territorial_organ__in=organs, is_deleted=False)
    if table["key"] in REQUEST_TABLE_CONFIG:
        return request_table_queryset(request, table["key"], organs, include_status=True)
    if request.GET.get("equipment_type") and hasattr(table["model"], "equipment_type"):
        qs = qs.filter(equipment_type=request.GET["equipment_type"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return qs


STATE_SNAPSHOT_TABLES = {
    "fire-extinguishers",
    "fire-alarm",
    "security-alarm",
    "service-housing",
}

STATE_SNAPSHOT_MODE_CHOICES = (
    ("current", "Последняя запись"),
    ("history", "История записей"),
)


def state_snapshot_mode(request, table_key):
    if table_key not in STATE_SNAPSHOT_TABLES:
        return ""
    return "history" if request.GET.get("state_mode") == "history" else "current"


def state_snapshot_queryset(request, table_key, qs):
    if state_snapshot_mode(request, table_key) == "history":
        return qs

    latest_id_for_organ = (
        qs.model.objects.filter(
            pk__in=qs.values("pk"),
            territorial_organ_id=OuterRef("territorial_organ_id"),
        )
        .order_by("-state_date", "-created_at", "-pk")
        .values("pk")[:1]
    )
    return qs.filter(pk=Subquery(latest_id_for_organ)).order_by("territorial_organ__name", "-state_date", "-created_at")


def request_date_filter_defaults(model, organs):
    oldest_date = model.objects.filter(territorial_organ__in=organs, is_deleted=False).aggregate(oldest=Min("request_date")).get("oldest")
    today = timezone.localdate()
    return {
        "date_from": oldest_date.isoformat() if oldest_date else today.isoformat(),
        "date_to": today.isoformat(),
    }


def request_date_filter_values(request, model, organs):
    defaults = request_date_filter_defaults(model, organs)
    date_from = request.GET.get("date_from") if "date_from" in request.GET else defaults["date_from"]
    date_to = request.GET.get("date_to") if "date_to" in request.GET else defaults["date_to"]
    return {"date_from": date_from, "date_to": date_to}


def request_table_date_filter_defaults(table_key, organs):
    return request_date_filter_defaults(REQUEST_TABLE_CONFIG[table_key]["model"], organs)


def request_table_date_filter_values(request, table_key, organs):
    return request_date_filter_values(request, REQUEST_TABLE_CONFIG[table_key]["model"], organs)


def build_search_q(search_fields, query):
    return build_text_search_q(search_fields, query)


def apply_casefold_search(qs, search_fields, query, distinct=False):
    return apply_text_search(qs, search_fields, query, distinct=distinct)


def request_table_queryset(request, table_key, organs, include_status=False):
    config = REQUEST_TABLE_CONFIG[table_key]
    qs = config["model"].objects.select_related("territorial_organ", "created_by", "updated_by")
    if config.get("prefetch"):
        qs = qs.prefetch_related(*config["prefetch"])
    qs = qs.filter(territorial_organ__in=organs, is_deleted=False)

    date_filters = request_table_date_filter_values(request, table_key, organs)
    date_from = parse_date(date_filters["date_from"])
    date_to = parse_date(date_filters["date_to"])
    if date_from:
        qs = qs.filter(request_date__gte=date_from)
    if date_to:
        qs = qs.filter(request_date__lte=date_to)
    if config.get("equipment_type_filter") and valid_equipment_type(request.GET.get("equipment_type")):
        qs = qs.filter(equipment_type=request.GET["equipment_type"])
    qs = apply_casefold_search(qs, config["search_fields"], request.GET.get("q", ""), distinct=config.get("distinct_search", False))
    if include_status and request.GET.get("status") in dict(ACTIVE_NEED_STATUS_CHOICES):
        qs = qs.filter(status=request.GET["status"])
    return qs




def format_filter_date(value):
    date = parse_date(value or "")
    return date.strftime("%d.%m.%Y") if date else value


def active_table_conditions(request, table_key, selected_organs, group_mode="requests"):
    conditions = []
    if len(selected_organs) > 1:
        conditions.append(f"выборочно: {len(selected_organs)} органов")
    if group_mode == "products":
        conditions.append("группировка: По ТМЦ")
    if group_mode == "organs":
        conditions.append("группировка: По территориальному органу")
    if group_mode == "dates":
        conditions.append("группировка: По дате")
    query = request.GET.get("q", "").strip()
    if query:
        conditions.append(f"поиск: {query}")
    status_labels = dict(ACTIVE_NEED_STATUS_CHOICES)
    status = request.GET.get("status")
    if status in status_labels:
        conditions.append(f"исполнение: {status_labels[status]}")
    if table_key == "citsizi-equipment":
        equipment_labels = dict(CitsiziEquipment._meta.get_field("equipment_type").choices)
        equipment_type = request.GET.get("equipment_type")
        if equipment_type in equipment_labels:
            conditions.append(f"тип техники: {equipment_labels[equipment_type]}")
    if request.GET.get("date_from"):
        conditions.append(f"с {format_filter_date(request.GET['date_from'])}")
    if request.GET.get("date_to"):
        conditions.append(f"по {format_filter_date(request.GET['date_to'])}")
    return conditions


FIRE_EXTINGUISHER_SOON_DAYS = 30
FIRE_EXTINGUISHER_EXPIRY_STATE_CHOICES = (
    ("", "Все сроки"),
    ("valid", "Годные"),
    ("soon", "Скоро истекает"),
    ("expired", "Истекшие"),
)
FIRE_EXTINGUISHER_EXPIRY_ORDER_CHOICES = (
    ("", "По порядку добавления"),
    ("soonest", "Сначала истекающие"),
    ("latest", "Сначала с большим сроком"),
)


def fire_extinguisher_expiry_window():
    today = timezone.localdate()
    return today, today + timedelta(days=FIRE_EXTINGUISHER_SOON_DAYS)


def fire_extinguisher_filtered_queryset(request, qs):
    today, soon_until = fire_extinguisher_expiry_window()
    expiry_state = request.GET.get("expiry_state", "")
    if expiry_state == "expired":
        qs = qs.filter(expiry_date__lt=today)
    elif expiry_state == "soon":
        qs = qs.filter(expiry_date__gte=today, expiry_date__lte=soon_until)
    elif expiry_state == "valid":
        qs = qs.filter(expiry_date__gt=soon_until)

    expiry_from = parse_date(request.GET.get("expiry_from", ""))
    expiry_to = parse_date(request.GET.get("expiry_to", ""))
    if expiry_from:
        qs = qs.filter(expiry_date__gte=expiry_from)
    if expiry_to:
        qs = qs.filter(expiry_date__lte=expiry_to)

    expiry_order = request.GET.get("expiry_order", "")
    if expiry_order == "latest":
        return qs.order_by("-expiry_date", "-state_date", "-created_at")
    if expiry_order == "soonest":
        return qs.order_by("expiry_date", "-state_date", "-created_at")
    return qs.order_by("-created_at", "-id")


def fire_extinguisher_active_conditions(request, selected_organs):
    conditions = []
    if len(selected_organs) > 1:
        conditions.append(f"выборочно: {len(selected_organs)} органов")
    expiry_state_labels = dict(FIRE_EXTINGUISHER_EXPIRY_STATE_CHOICES)
    expiry_state = request.GET.get("expiry_state", "")
    if expiry_state:
        conditions.append(f"срок: {expiry_state_labels.get(expiry_state, expiry_state)}")
    expiry_order_labels = dict(FIRE_EXTINGUISHER_EXPIRY_ORDER_CHOICES)
    expiry_order = request.GET.get("expiry_order", "")
    if expiry_order:
        conditions.append(f"сортировка: {expiry_order_labels.get(expiry_order, expiry_order)}")
    if request.GET.get("expiry_from"):
        conditions.append(f"срок с {format_filter_date(request.GET['expiry_from'])}")
    if request.GET.get("expiry_to"):
        conditions.append(f"срок по {format_filter_date(request.GET['expiry_to'])}")
    return conditions




























def valid_equipment_type(value):
    return value in {choice[0] for choice in CitsiziEquipment._meta.get_field("equipment_type").choices}
