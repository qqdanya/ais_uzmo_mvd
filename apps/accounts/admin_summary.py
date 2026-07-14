from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Min, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import NeedStatus, RequestStatusHistory
from apps.requests_app.permissions import can_view
from apps.requests_app.registry import TABLES

from .admin_common import month_bounds, request_number
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
DYNAMICS_MONTH_LABELS = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


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
        "label": f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}",
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


def request_period_q(period):
    """Q equivalent of apply_request_period, usable inside filtered aggregates."""
    condition = Q()
    if period["period"] == "all":
        return condition
    if period["date_from"]:
        condition &= Q(request_date__gte=period["date_from"])
    if period["date_to"]:
        condition &= Q(request_date__lte=period["date_to"])
    return condition


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


def _changed_at_bounds(date_from, date_to):
    """Convert local calendar-date bounds into an aware [start, end)
    datetime range equivalent to changed_at__date__gte/__lte, but as a raw
    comparison instead of a per-row local-date extraction.

    changed_at__date__gte/__lte forces SQLite to evaluate a timezone-
    converting function against every row that matches the rest of the
    filter before it can even check the date bound - at tens of thousands
    of rows per (content_type, status), that dwarfs the actual date-ranged
    result. A plain changed_at >= / < comparison can use a B-tree range
    scan on the existing (content_type, new_status, changed_at) index
    instead, letting SQLite skip straight to the matching rows.
    """
    start = timezone.make_aware(datetime.combine(date_from, time.min)) if date_from else None
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min)) if date_to else None
    return start, end


def _period_changed_at_bounds(period):
    return _changed_at_bounds(period["date_from"], period["date_to"])


def status_history_qs(table, qs, status, period=None):
    history = RequestStatusHistory.objects.filter(
        content_type=table.get("content_type") or content_type_for_model(table["model"]),
        object_id__in=qs.values("pk"),
        new_status=status,
    )
    if period and period["period"] != "all":
        start, end = _period_changed_at_bounds(period)
        if start:
            history = history.filter(changed_at__gte=start)
        if end:
            history = history.filter(changed_at__lt=end)
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
            start, end = _changed_at_bounds(days[0], days[-1])
            history = history.filter(changed_at__gte=start, changed_at__lt=end)
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


def table_base_metrics(tables, organs, period):
    """Fetch total/in-work/stale counters with one scan per request table."""
    period_filter = request_period_q(period)
    stale_before = stale_cutoff_date()
    return {
        table["key"]: base_queryset(table, organs).aggregate(
            total=Count("pk", filter=period_filter),
            in_work=Count("pk", filter=Q(status=NeedStatus.IN_WORK)),
            stale=Count("pk", filter=Q(status=NeedStatus.IN_WORK, request_date__lte=stale_before)),
        )
        for table in tables
    }


def build_kpi(tables, organs, period, history_flags=None, base_metrics=None):
    totals = Counter()
    base_metrics = base_metrics or table_base_metrics(tables, organs, period)
    for table in tables:
        qs = base_queryset(table, organs)
        metrics = base_metrics[table["key"]]
        totals["total"] += metrics["total"]
        totals["in_work"] += metrics["in_work"]
        done_flag = history_flags.get((table["key"], NeedStatus.DONE)) if history_flags else None
        rejected_flag = history_flags.get((table["key"], NeedStatus.REJECTED)) if history_flags else None
        totals["done"] += count_status_changed(table, qs, NeedStatus.DONE, period, done_flag)
        totals["rejected"] += count_status_changed(table, qs, NeedStatus.REJECTED, period, rejected_flag)
        totals["stale"] += metrics["stale"]
    return {
        "total": totals["total"],
        "in_work": totals["in_work"],
        "done": totals["done"],
        "rejected": totals["rejected"],
        "stale": totals["stale"],
    }


def dynamics_bucket_key(day, granularity):
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def dynamics_bucket_label(bucket_days, granularity):
    first_day = bucket_days[0]
    last_day = bucket_days[-1]
    if granularity == "month":
        return f"{DYNAMICS_MONTH_LABELS[first_day.month - 1]} {first_day.year}"
    if granularity == "week" and first_day != last_day:
        return f"{first_day:%d.%m}–{last_day:%d.%m}"
    return first_day.strftime("%d.%m")


def build_dynamics_series(days, counters, granularity):
    buckets = {}
    for day in days:
        key = dynamics_bucket_key(day, granularity)
        bucket = buckets.setdefault(
            key,
            {"days": [], **{series_name: 0 for series_name in counters}},
        )
        bucket["days"].append(day)
        for series_name, counter in counters.items():
            bucket[series_name] += counter[day]
    return {
        "labels": [dynamics_bucket_label(bucket["days"], granularity) for bucket in buckets.values()],
        **{
            series_name: [bucket[series_name] for bucket in buckets.values()]
            for series_name in counters
        },
    }


def default_dynamics_granularity(days):
    if len(days) > 180:
        return "month"
    if len(days) > 45:
        return "week"
    return "day"


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
    counters = {"incoming": incoming, "done": done, "rejected": rejected}
    return {
        "default_granularity": default_dynamics_granularity(days),
        "day": build_dynamics_series(days, counters, "day"),
        "week": build_dynamics_series(days, counters, "week"),
        "month": build_dynamics_series(days, counters, "month"),
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


def build_department_load(tables, organs, base_metrics=None):
    departments = active_departments_by_slug()
    rows_by_department = defaultdict(int)
    for table in tables:
        in_work = base_metrics[table["key"]]["in_work"] if base_metrics else base_queryset(table, organs).filter(status=NeedStatus.IN_WORK).count()
        rows_by_department[table["department"]] += in_work
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


SUMMARY_DATA_CACHE_SECONDS = 45


def summary_data_cache_key(request, metric):
    # Scoped by user (not just role) to stay correct if permissions ever get
    # more granular than "admin sees everything" - a stale hit here would
    # only affect the read-only KPI/chart JSON, never a write or a
    # permission check, so a coarse per-user key is a fine tradeoff.
    raw_ids = request.GET.getlist("organ_ids")
    if not raw_ids and request.GET.get("organ_ids"):
        raw_ids = request.GET["organ_ids"].split(",")
    organ_ids = ",".join(sorted({value for value in raw_ids if str(value).isdigit()}))
    return ":".join(
        [
            "admin-summary-data",
            "v2",
            str(request.user.pk),
            metric,
            request.GET.get("period", ""),
            request.GET.get("date_from", ""),
            request.GET.get("date_to", ""),
            "empty" if request.GET.get("organ_filter_empty") == "1" else "",
            organ_ids,
        ]
    )


def build_summary_payload(request, metric="in_work", *, available_organs=None, tables=None):
    period = parse_period(request)
    available_organs = available_organs if available_organs is not None else available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    tables = tables if tables is not None else list(request_tables())
    history_flags = status_history_flags(tables, organs)
    base_metrics = table_base_metrics(tables, organs, period)
    return {
        "period": serialize_period(period),
        "selected_organs": [organ.pk for organ in organs],
        "selected_organs_count": len(organs),
        "kpi": build_kpi(tables, organs, period, history_flags, base_metrics),
        "dynamics": build_dynamics(tables, organs, period, history_flags),
        "org_chart": build_org_chart(tables, organs, period, metric=metric, history_flags=history_flags),
        "department_load": build_department_load(tables, organs, base_metrics),
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
