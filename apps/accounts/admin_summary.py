from calendar import monthrange
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Min
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import NeedStatus, RequestStatusHistory
from apps.requests_app.permissions import can_view
from apps.requests_app.registry import TABLES

from .admin_common import request_number
from .admin_thresholds import get_request_stale_workdays
from .business_days import business_days_inclusive, subtract_business_days_inclusive


REQUEST_TABLE_REQUIRED_FIELDS = {"status", "request_date", "territorial_organ", "is_deleted"}
COMPLETED_DATE_FIELDS = {
    "citsizi-equipment": "due_date",
    "tmc-requests": "due_date",
}
STATUS_LABELS = {
    NeedStatus.IN_WORK: "В работе",
    NeedStatus.DONE: "Исполнено",
    NeedStatus.REJECTED: "Отклонено",
}


def _table_field_names(model):
    return {field.name for field in model._meta.fields}


def _summary_table(table, department_slug):
    model = table["model"]
    return {
        **table,
        "department": table.get("department") or department_slug,
        "field_names": _table_field_names(model),
        "content_type": ContentType.objects.get_for_model(model, for_concrete_model=False),
    }


def request_tables():
    """Yield registry records that behave as request tables."""
    seen = set()
    for department_slug, tables in TABLES.items():
        for table in tables:
            model = table["model"]
            if model in seen:
                continue
            field_names = _table_field_names(model)
            if REQUEST_TABLE_REQUIRED_FIELDS.issubset(field_names):
                seen.add(model)
                yield _summary_table(table, department_slug)


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


def serialize_period(period):
    return {
        "code": period["period"],
        "date_from": period["date_from"].isoformat() if period["date_from"] else "",
        "date_to": period["date_to"].isoformat() if period["date_to"] else "",
        "label": period["label"],
    }


def available_organs_for_user(user):
    organs = (
        TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True)
        .prefetch_related("children")
        .order_by("order_number", "name")
    )
    return [organ for organ in organs if can_view(user, organ)]


def selected_organs(request, available_organs):
    available_by_id = {organ.pk: organ for organ in available_organs}
    if request.GET.get("organ_filter_empty") == "1":
        return []
    raw_ids = request.GET.getlist("organ_ids")
    if not raw_ids and request.GET.get("organ_ids"):
        raw_ids = request.GET["organ_ids"].split(",")
    ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not ids:
        return available_organs
    return [available_by_id[pk] for pk in ids if pk in available_by_id]


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


def period_from_days(days):
    return {"period": "custom", "date_from": days[0], "date_to": days[-1]}


def table_has_field(table, field_name):
    return field_name in table["field_names"]


def base_queryset(table, organs):
    return table["model"].objects.filter(is_deleted=False, territorial_organ__in=organs)


def content_type_for_model(model):
    return ContentType.objects.get_for_model(model, for_concrete_model=False)


def status_history_qs(table, qs, status, period=None):
    history = RequestStatusHistory.objects.filter(
        content_type=table.get("content_type") or content_type_for_model(table["model"]),
        object_id__in=qs.values("pk"),
        new_status=status,
    )
    if period and period["period"] != "all":
        history = history.filter(changed_at__date__gte=period["date_from"], changed_at__date__lte=period["date_to"])
    return history


def has_status_history(table, qs, status):
    return status_history_qs(table, qs, status).exists()


def completed_date_field(table):
    field_name = COMPLETED_DATE_FIELDS.get(table["key"], "completed_at")
    return field_name if table_has_field(table, field_name) else None


def count_status_changed(table, qs, status, period, has_history=None):
    if has_history is None:
        has_history = has_status_history(table, qs, status)
    if has_history:
        return status_history_qs(table, qs, status, period).values("object_id").distinct().count()

    # Fallback for imported/old rows without status history.
    if status == NeedStatus.DONE:
        field_name = completed_date_field(table)
        if field_name:
            return apply_date_period(qs.filter(status=status), field_name, period).count()
    return apply_request_period(qs.filter(status=status), period).count()


def period_day_labels(period, organs, tables=None):
    if period["period"] != "all" and period["date_from"] and period["date_to"]:
        start, end = period["date_from"], period["date_to"]
    else:
        oldest_dates = []
        for table in tables or request_tables():
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


def add_status_history_series(counter, table, qs, status, days, has_history=None):
    day_set = set(days)
    if has_history is None:
        has_history = has_status_history(table, qs, status)
    if has_history:
        history = status_history_qs(table, qs, status)
        if day_set:
            history = history.filter(changed_at__date__gte=days[0], changed_at__date__lte=days[-1])
        for row in history.annotate(day=TruncDate("changed_at")).values("day").annotate(total=Count("object_id", distinct=True)):
            if row["day"]:
                counter[row["day"]] += row["total"]
        return

    # Fallback for old rows without status history.
    if status == NeedStatus.DONE:
        field_name = completed_date_field(table)
        if field_name:
            add_date_field_series(
                counter,
                qs.filter(status=status).exclude(**{f"{field_name}__isnull": True}),
                field_name,
            )
            return
    add_request_date_series(counter, qs.filter(status=status))


def stale_cutoff_date():
    return subtract_business_days_inclusive(timezone.localdate(), get_request_stale_workdays() + 1)


def build_kpi(tables, organs, period, history_flags=None):
    totals = Counter()
    stale_before = stale_cutoff_date()
    for table in tables:
        qs = base_queryset(table, organs)
        totals["total"] += apply_request_period(qs, period).count()
        totals["in_work"] += qs.filter(status=NeedStatus.IN_WORK).count()
        done_flag = history_flags.get((table["key"], NeedStatus.DONE)) if history_flags else None
        rejected_flag = history_flags.get((table["key"], NeedStatus.REJECTED)) if history_flags else None
        totals["done"] += count_status_changed(table, qs, NeedStatus.DONE, period, done_flag)
        totals["rejected"] += count_status_changed(table, qs, NeedStatus.REJECTED, period, rejected_flag)
        totals["stale"] += qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).count()
    return {
        "total": totals["total"],
        "in_work": totals["in_work"],
        "done": totals["done"],
        "rejected": totals["rejected"],
        "stale": totals["stale"],
    }


def build_dynamics(tables, organs, period, history_flags=None):
    days = period_day_labels(period, organs, tables=tables)
    incoming = Counter()
    done = Counter()
    rejected = Counter()
    dynamics_period = period_from_days(days)
    for table in tables:
        qs = base_queryset(table, organs)
        done_flag = history_flags.get((table["key"], NeedStatus.DONE)) if history_flags else None
        rejected_flag = history_flags.get((table["key"], NeedStatus.REJECTED)) if history_flags else None
        add_request_date_series(incoming, apply_request_period(qs, dynamics_period))
        add_status_history_series(done, table, qs, NeedStatus.DONE, days, done_flag)
        add_status_history_series(rejected, table, qs, NeedStatus.REJECTED, days, rejected_flag)
    return {
        "labels": [day.strftime("%d.%m") for day in days],
        "incoming": [incoming[day] for day in days],
        "done": [done[day] for day in days],
        "rejected": [rejected[day] for day in days],
    }


def group_by_organ_for_metric(table, qs, period, metric, stale_before, has_history=None):
    if metric == "total":
        return apply_request_period(qs, period).values("territorial_organ_id").annotate(total=Count("pk"))
    if metric == "done":
        return group_by_organ_for_status(table, qs, period, NeedStatus.DONE, has_history)
    if metric == "rejected":
        return group_by_organ_for_status(table, qs, period, NeedStatus.REJECTED, has_history)
    if metric == "stale":
        return qs.filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before).values("territorial_organ_id").annotate(total=Count("pk"))
    return qs.filter(status=NeedStatus.IN_WORK).values("territorial_organ_id").annotate(total=Count("pk"))


def group_by_organ_for_status(table, qs, period, status, has_history=None):
    if has_history is None:
        has_history = has_status_history(table, qs, status)
    if has_history:
        object_ids = status_history_qs(table, qs, status, period).values("object_id")
        return qs.filter(pk__in=object_ids).values("territorial_organ_id").annotate(total=Count("pk", distinct=True))
    return apply_request_period(qs.filter(status=status), period).values("territorial_organ_id").annotate(total=Count("pk"))


def add_percent(rows):
    max_value = max([row["value"] for row in rows], default=0) or 1
    for row in rows:
        row["percent"] = round(row["value"] * 100 / max_value)
    return rows


def build_org_chart(tables, organs, period, metric="in_work", history_flags=None):
    org_rows = {organ.pk: {"id": organ.pk, "name": organ.name, "value": 0} for organ in organs}
    stale_before = stale_cutoff_date()
    for table in tables:
        qs = base_queryset(table, organs)
        has_history = history_flags.get((table["key"], metric)) if history_flags and metric in (NeedStatus.DONE, NeedStatus.REJECTED) else None
        grouped = group_by_organ_for_metric(table, qs, period, metric, stale_before, has_history)
        for row in grouped:
            if row["territorial_organ_id"] in org_rows:
                org_rows[row["territorial_organ_id"]]["value"] += row["total"]
    rows = sorted(org_rows.values(), key=lambda item: item["value"], reverse=True)
    return add_percent(rows)


def active_departments_by_slug():
    return {item.slug: item.name for item in Department.objects.filter(is_active=True)}


def build_department_load(tables, organs):
    departments = active_departments_by_slug()
    rows_by_department = defaultdict(int)
    for table in tables:
        rows_by_department[table["department"]] += base_queryset(table, organs).filter(status=NeedStatus.IN_WORK).count()
    rows = [
        {"slug": slug, "name": departments.get(slug, slug), "value": value}
        for slug, value in rows_by_department.items()
    ]
    rows.sort(key=lambda item: item["value"], reverse=True)
    return add_percent(rows)


def build_attention_requests(tables, organs, limit=10):
    stale_before = stale_cutoff_date()
    today = timezone.localdate()
    departments = active_departments_by_slug()
    items = []
    for table in tables:
        qs = (
            base_queryset(table, organs)
            .select_related("territorial_organ")
            .filter(status=NeedStatus.IN_WORK, request_date__lte=stale_before)
            .order_by("request_date", "pk")[:limit]
        )
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
                    "detail_url": reverse("admin_request_detail", kwargs={"table_key": table["key"], "pk": obj.pk}),
                }
            )
    items.sort(key=lambda item: item["days"], reverse=True)
    return items[:limit]


def status_history_flags(tables, organs):
    """Precompute has_status_history() once per (table, status) pair.

    build_kpi, build_dynamics and build_org_chart each independently ask "does
    this table have any RequestStatusHistory rows for this status" for the
    same (table, organs) scope. The answer only depends on table/organs/status,
    not on period, so computing it once here and passing it down avoids
    repeating the same exists() query 2-3x per table on every summary load.
    """
    flags = {}
    for table in tables:
        qs = base_queryset(table, organs)
        for status in (NeedStatus.DONE, NeedStatus.REJECTED):
            flags[(table["key"], status)] = has_status_history(table, qs, status)
    return flags


def build_summary_payload(request, metric="in_work", *, available_organs=None, tables=None):
    period = parse_period(request)
    available_organs = available_organs if available_organs is not None else available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    tables = tables if tables is not None else list(request_tables())
    history_flags = status_history_flags(tables, organs)
    return {
        "period": serialize_period(period),
        "selected_organs": [organ.pk for organ in organs],
        "selected_organs_count": len(organs),
        "kpi": build_kpi(tables, organs, period, history_flags),
        "dynamics": build_dynamics(tables, organs, period, history_flags),
        "org_chart": build_org_chart(tables, organs, period, metric=metric, history_flags=history_flags),
        "department_load": build_department_load(tables, organs),
        "attention_requests": build_attention_requests(tables, organs),
        "request_stale_workdays": get_request_stale_workdays(),
    }


def build_summary_context(request):
    # The KPI/dynamics/org-chart/department-load/attention aggregates are the
    # most expensive part of this page and aren't needed for first paint —
    # admin_summary.js fetches them from admin_summary_data (the same
    # build_summary_payload()) right after load and fills them in. Rendering
    # summary_payload as empty here just means the shell paints instantly
    # instead of blocking on every one of those aggregate queries twice
    # (once here, once again for the immediate client-side refresh).
    return {
        "organs": available_organs_for_user(request.user),
        "summary_payload": {},
        "request_stale_workdays": get_request_stale_workdays(),
        "summary_org_metric": request.GET.get("org_metric", "in_work"),
    }
