from calendar import monthrange
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Min, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import NeedStatus, RequestStatusHistory
from apps.requests_app.permissions import can_view
from apps.requests_app.registry import TABLES

from .business_days import business_days_inclusive, subtract_business_days_inclusive


COMPLETED_DATE_FIELDS = {
    "citsizi-equipment": "due_date",
    "tmc-requests": "due_date",
}

STATUS_LABELS = {
    NeedStatus.IN_WORK: "В работе",
    NeedStatus.DONE: "Исполнено",
    NeedStatus.REJECTED: "Отклонено",
}


def request_tables():
    """Yield registry records that behave as request tables."""
    seen = set()
    for department_slug, tables in TABLES.items():
        for table in tables:
            model = table["model"]
            if model in seen:
                continue
            field_names = {field.name for field in model._meta.fields}
            if {"status", "request_date", "territorial_organ", "is_deleted"}.issubset(field_names):
                seen.add(model)
                yield {**table, "department": table.get("department") or department_slug}


def month_bounds(day):
    first = day.replace(day=1)
    last = day.replace(day=monthrange(day.year, day.month)[1])
    return first, last


def parse_period(request):
    today = timezone.localdate()
    requested_period = request.GET.get("period", "")
    if requested_period == "all":
        return {
            "period": "all",
            "date_from": None,
            "date_to": None,
            "label": "за всё время",
        }

    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    if not date_from or not date_to:
        date_from, date_to = month_bounds(today)
        requested_period = "current_month"
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return {
        "period": requested_period or "custom",
        "date_from": date_from,
        "date_to": date_to,
        "label": f"{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}",
    }


def available_organs_for_user(user):
    organs = TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).prefetch_related("children").order_by("order_number", "name")
    return [organ for organ in organs if can_view(user, organ)]


def selected_organs(request, available_organs):
    available_by_id = {organ.pk: organ for organ in available_organs}
    raw_ids = request.GET.getlist("organ_ids")
    if not raw_ids and request.GET.get("organ_ids"):
        raw_ids = request.GET["organ_ids"].split(",")
    ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not ids:
        return available_organs
    return [available_by_id[pk] for pk in ids if pk in available_by_id] or available_organs


def apply_request_period(qs, period):
    if period["period"] == "all":
        return qs
    if period["date_from"]:
        qs = qs.filter(request_date__gte=period["date_from"])
    if period["date_to"]:
        qs = qs.filter(request_date__lte=period["date_to"])
    return qs


def apply_date_period(qs, field_name, period):
    if period["period"] == "all":
        return qs
    if period["date_from"]:
        qs = qs.filter(**{f"{field_name}__gte": period["date_from"]})
    if period["date_to"]:
        qs = qs.filter(**{f"{field_name}__lte": period["date_to"]})
    return qs


def base_queryset(table, organs):
    return table["model"].objects.filter(is_deleted=False, territorial_organ__in=organs)


def content_type_for_model(model):
    return ContentType.objects.get_for_model(model, for_concrete_model=False)


def status_history_qs(table, qs, status, period=None):
    history = RequestStatusHistory.objects.filter(
        content_type=content_type_for_model(table["model"]),
        object_id__in=qs.values("pk"),
        new_status=status,
    )
    if period and period["period"] != "all":
        history = history.filter(changed_at__date__gte=period["date_from"], changed_at__date__lte=period["date_to"])
    return history


def has_status_history(table, qs, status):
    return status_history_qs(table, qs, status).exists()


def count_status_changed(table, qs, status, period):
    if has_status_history(table, qs, status):
        return status_history_qs(table, qs, status, period).values("object_id").distinct().count()

    # Fallback for imported/old rows without status history.
    if status == NeedStatus.DONE:
        field_name = COMPLETED_DATE_FIELDS.get(table["key"], "completed_at")
        if field_name in {field.name for field in table["model"]._meta.fields}:
            return apply_date_period(qs.filter(status=status), field_name, period).count()
    return apply_request_period(qs.filter(status=status), period).count()


def period_day_labels(period, organs):
    if period["period"] != "all" and period["date_from"] and period["date_to"]:
        start, end = period["date_from"], period["date_to"]
    else:
        oldest_dates = []
        for table in request_tables():
            value = base_queryset(table, organs).aggregate(oldest=Min("request_date")).get("oldest")
            if value:
                oldest_dates.append(value)
        end = timezone.localdate()
        start = min(oldest_dates) if oldest_dates else end
    # Keep the chart readable if a very old database is opened.
    if (end - start).days > 365:
        start = end - timedelta(days=365)
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def add_date_field_series(counter, qs, field_name):
    """Group rows by a date-like field without forcing DateField through SQLite datetime casts."""
    model_field = qs.model._meta.get_field(field_name)

    if model_field.get_internal_type() == "DateTimeField":
        rows = qs.annotate(day=TruncDate(field_name)).values("day").annotate(total=Count("pk"))
        for row in rows:
            if row["day"]:
                counter[row["day"]] += row["total"]
        return

    rows = qs.values(field_name).annotate(total=Count("pk"))
    for row in rows:
        day = row.get(field_name)
        if day:
            counter[day] += row["total"]


def add_request_date_series(counter, qs):
    add_date_field_series(counter, qs, "request_date")


def add_status_history_series(counter, table, qs, status, days):
    day_set = set(days)
    if has_status_history(table, qs, status):
        history = status_history_qs(table, qs, status)
        if day_set:
            history = history.filter(changed_at__date__gte=days[0], changed_at__date__lte=days[-1])
        for row in history.annotate(day=TruncDate("changed_at")).values("day").annotate(total=Count("object_id", distinct=True)):
            if row["day"]:
                counter[row["day"]] += row["total"]
        return

    # Fallback for old rows without status history.
    if status == NeedStatus.DONE:
        field_name = COMPLETED_DATE_FIELDS.get(table["key"], "completed_at")
        if field_name in {field.name for field in table["model"]._meta.fields}:
            add_date_field_series(
                counter,
                qs.filter(status=status).exclude(**{f"{field_name}__isnull": True}),
                field_name,
            )
            return
    add_request_date_series(counter, qs.filter(status=status))


def build_kpi(tables, organs, period):
    totals = Counter()
    stale_before = subtract_business_days_inclusive(timezone.localdate(), 15)
    for table in tables:
        qs = base_queryset(table, organs)
        totals["total"] += apply_request_period(qs, period).count()
        totals["in_work"] += qs.filter(status=NeedStatus.IN_WORK).count()
        totals["done"] += count_status_changed(table, qs, NeedStatus.DONE, period)
        totals["rejected"] += count_status_changed(table, qs, NeedStatus.REJECTED, period)
        totals["stale"] += qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).count()
    return {
        "total": totals["total"],
        "in_work": totals["in_work"],
        "done": totals["done"],
        "rejected": totals["rejected"],
        "stale": totals["stale"],
    }


def build_dynamics(tables, organs, period):
    days = period_day_labels(period, organs)
    incoming = Counter()
    done = Counter()
    rejected = Counter()
    for table in tables:
        qs = base_queryset(table, organs)
        add_request_date_series(incoming, apply_request_period(qs, {"period": "custom", "date_from": days[0], "date_to": days[-1]}))
        add_status_history_series(done, table, qs, NeedStatus.DONE, days)
        add_status_history_series(rejected, table, qs, NeedStatus.REJECTED, days)
    return {
        "labels": [day.strftime("%d.%m") for day in days],
        "incoming": [incoming[day] for day in days],
        "done": [done[day] for day in days],
        "rejected": [rejected[day] for day in days],
    }


def build_org_chart(tables, organs, period, metric="in_work"):
    org_rows = {organ.pk: {"id": organ.pk, "name": organ.name, "value": 0} for organ in organs}
    stale_before = subtract_business_days_inclusive(timezone.localdate(), 15)
    for table in tables:
        qs = base_queryset(table, organs)
        if metric == "total":
            grouped = apply_request_period(qs, period).values("territorial_organ_id").annotate(total=Count("pk"))
        elif metric == "done":
            # Prefer status history; fallback to completed/request date only for old rows without history.
            if has_status_history(table, qs, NeedStatus.DONE):
                object_ids = status_history_qs(table, qs, NeedStatus.DONE, period).values("object_id")
                grouped = qs.filter(pk__in=object_ids).values("territorial_organ_id").annotate(total=Count("pk", distinct=True))
            else:
                grouped = apply_request_period(qs.filter(status=NeedStatus.DONE), period).values("territorial_organ_id").annotate(total=Count("pk"))
        elif metric == "rejected":
            if has_status_history(table, qs, NeedStatus.REJECTED):
                object_ids = status_history_qs(table, qs, NeedStatus.REJECTED, period).values("object_id")
                grouped = qs.filter(pk__in=object_ids).values("territorial_organ_id").annotate(total=Count("pk", distinct=True))
            else:
                grouped = apply_request_period(qs.filter(status=NeedStatus.REJECTED), period).values("territorial_organ_id").annotate(total=Count("pk"))
        elif metric == "stale":
            grouped = qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).values("territorial_organ_id").annotate(total=Count("pk"))
        else:
            grouped = qs.filter(status=NeedStatus.IN_WORK).values("territorial_organ_id").annotate(total=Count("pk"))
        for row in grouped:
            if row["territorial_organ_id"] in org_rows:
                org_rows[row["territorial_organ_id"]]["value"] += row["total"]
    rows = sorted(org_rows.values(), key=lambda item: item["value"], reverse=True)
    max_value = max([row["value"] for row in rows], default=0) or 1
    for row in rows:
        row["percent"] = round(row["value"] * 100 / max_value)
    return rows


def build_department_load(tables, organs):
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    rows_by_department = defaultdict(int)
    for table in tables:
        rows_by_department[table["department"]] += base_queryset(table, organs).filter(status=NeedStatus.IN_WORK).count()
    rows = [
        {"slug": slug, "name": departments.get(slug, slug), "value": value}
        for slug, value in rows_by_department.items()
    ]
    rows.sort(key=lambda item: item["value"], reverse=True)
    max_value = max([row["value"] for row in rows], default=0) or 1
    for row in rows:
        row["percent"] = round(row["value"] * 100 / max_value)
    return rows


def request_number(obj):
    return getattr(obj, "request_number", None) or str(obj.pk)


def build_attention_requests(tables, organs, limit=10):
    stale_before = subtract_business_days_inclusive(timezone.localdate(), 15)
    today = timezone.localdate()
    departments = {item.slug: item.name for item in Department.objects.filter(is_active=True)}
    items = []
    for table in tables:
        qs = base_queryset(table, organs).select_related("territorial_organ").filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).order_by("request_date", "pk")[:limit]
        for obj in qs:
            items.append(
                {
                    "id": obj.pk,
                    "number": request_number(obj),
                    "title": str(obj),
                    "department": departments.get(table["department"], table["department"]),
                    "table": table["title"],
                    "organ": obj.territorial_organ.name,
                    "request_date": obj.request_date.strftime("%d.%m.%Y"),
                    "days": business_days_inclusive(obj.request_date, today),
                }
            )
    items.sort(key=lambda item: item["days"], reverse=True)
    return items[:limit]


def build_summary_payload(request, metric="in_work"):
    period = parse_period(request)
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    tables = list(request_tables())
    kpi = build_kpi(tables, organs, period)
    payload = {
        "period": {
            "code": period["period"],
            "date_from": period["date_from"].isoformat() if period["date_from"] else "",
            "date_to": period["date_to"].isoformat() if period["date_to"] else "",
            "label": period["label"],
        },
        "selected_organs": [organ.pk for organ in organs],
        "selected_organs_count": len(organs),
        "kpi": kpi,
        "dynamics": build_dynamics(tables, organs, period),
        "org_chart": build_org_chart(tables, organs, period, metric=metric),
        "department_load": build_department_load(tables, organs),
        "attention_requests": build_attention_requests(tables, organs),
    }
    return payload


def build_summary_context(request):
    available_organs = available_organs_for_user(request.user)
    payload = build_summary_payload(request, metric=request.GET.get("org_metric", "in_work"))
    return {
        "organs": available_organs,
        "summary_payload": payload,
        "summary_org_metric": request.GET.get("org_metric", "in_work"),
    }
