"""Grouping helpers for request table views and exports."""

from django.db.models import Count, Q, Sum

from apps.requests_app.models import NeedStatus, TmcRequestItem


def request_status_stats(qs):
    counts = qs.aggregate(
        in_work_count=Count("id", filter=Q(status=NeedStatus.IN_WORK)),
        done_count=Count("id", filter=Q(status=NeedStatus.DONE)),
        rejected_count=Count("id", filter=Q(status=NeedStatus.REJECTED)),
    )
    return {key: counts.get(key) or 0 for key in ("in_work_count", "done_count", "rejected_count")}


def tmc_grouped_rows(qs):
    return (
        TmcRequestItem.objects.filter(request__in=qs)
        .values("product_id", "product__name", "name", "unit")
        .annotate(
            request_count=Count("request_id", distinct=True),
            organ_count=Count("request__territorial_organ_id", distinct=True),
            total_quantity=Sum("quantity"),
        )
        .order_by("-request_count", "-total_quantity", "product__name", "name", "unit")
    )


def tmc_organ_grouped_rows(qs):
    rows = request_organ_grouped_rows(qs)
    quantities = {
        row["request__territorial_organ_id"]: row
        for row in TmcRequestItem.objects.filter(request__in=qs)
        .values("request__territorial_organ_id", "request__territorial_organ__name")
        .annotate(
            request_count=Count("request_id", distinct=True),
            position_count=Count("id"),
            total_quantity=Sum("quantity"),
        )
    }
    for row in rows:
        item_row = quantities.get(row["territorial_organ_id"], {})
        row["request__territorial_organ__name"] = row.get("territorial_organ__name")
        row["position_count"] = item_row.get("position_count") or 0
        row["total_quantity"] = item_row.get("total_quantity") or 0
    return rows


def tmc_date_grouped_rows(qs):
    rows = request_date_grouped_rows(qs)
    quantities = {
        row["request__request_date"]: row
        for row in TmcRequestItem.objects.filter(request__in=qs)
        .values("request__request_date")
        .annotate(position_count=Count("id"), total_quantity=Sum("quantity"))
    }
    for row in rows:
        item_row = quantities.get(row["request_date"], {})
        row["position_count"] = item_row.get("position_count") or 0
        row["total_quantity"] = item_row.get("total_quantity") or 0
    return rows


def request_date_grouped_rows(qs):
    return list(
        qs.values("request_date")
        .annotate(
            request_count=Count("id"),
            organ_count=Count("territorial_organ_id", distinct=True),
            in_work_count=Count("id", filter=Q(status=NeedStatus.IN_WORK)),
            done_count=Count("id", filter=Q(status=NeedStatus.DONE)),
            rejected_count=Count("id", filter=Q(status=NeedStatus.REJECTED)),
        )
        .order_by("-request_date")
    )


def request_organ_grouped_rows(qs):
    return list(
        qs.values("territorial_organ_id", "territorial_organ__name")
        .annotate(
            request_count=Count("id"),
            in_work_count=Count("id", filter=Q(status=NeedStatus.IN_WORK)),
            done_count=Count("id", filter=Q(status=NeedStatus.DONE)),
            rejected_count=Count("id", filter=Q(status=NeedStatus.REJECTED)),
        )
        .order_by("territorial_organ__name")
    )


def tmc_grouped_summary(qs, grouped_count):
    items = TmcRequestItem.objects.filter(request__in=qs)
    request_counts = qs.aggregate(
        request_count=Count("id"),
        organ_count=Count("territorial_organ_id", distinct=True),
    )
    return {
        "position_count": grouped_count,
        "request_count": request_counts["request_count"],
        "organ_count": request_counts["organ_count"],
        "total_quantity": items.aggregate(total=Sum("quantity")).get("total") or 0,
    }


def tmc_organ_grouped_summary(qs, grouped_count):
    items = TmcRequestItem.objects.filter(request__in=qs)
    item_counts = items.aggregate(position_count=Count("id"), total_quantity=Sum("quantity"))
    return {
        "organ_count": grouped_count,
        "request_count": qs.count(),
        "position_count": item_counts["position_count"],
        "total_quantity": item_counts["total_quantity"] or 0,
    }


def tmc_date_grouped_summary(qs, grouped_count):
    items = TmcRequestItem.objects.filter(request__in=qs)
    summary = request_grouped_summary(qs, date_count=grouped_count)
    item_counts = items.aggregate(position_count=Count("id"), total_quantity=Sum("quantity"))
    summary.update({
        "date_count": grouped_count,
        "position_count": item_counts["position_count"],
        "total_quantity": item_counts["total_quantity"] or 0,
    })
    return summary


def request_grouped_summary(qs, date_count=None, organ_count=None):
    summary = qs.aggregate(
        in_work_count=Count("id", filter=Q(status=NeedStatus.IN_WORK)),
        done_count=Count("id", filter=Q(status=NeedStatus.DONE)),
        rejected_count=Count("id", filter=Q(status=NeedStatus.REJECTED)),
        request_count=Count("id"),
        **({} if organ_count is not None else {"organ_count": Count("territorial_organ_id", distinct=True)}),
    )
    summary.update(
        {
            "organ_count": organ_count if organ_count is not None else summary["organ_count"],
        }
    )
    if date_count is not None:
        summary["date_count"] = date_count
    return summary


def attach_tmc_drilldown_querystrings(rows, base_querystring):
    for row in rows:
        product_name = row.get("product__name") or row.get("name") or ""
        drilldown_querystring = base_querystring.copy()
        drilldown_querystring["q"] = product_name
        row["drilldown_querystring"] = drilldown_querystring.urlencode()
    return rows


def request_group_mode(request, table_key, is_multi_organ):
    group = request.GET.get("group")
    if table_key == "tmc-requests" and group == "products":
        return "products"
    if group == "organs" and is_multi_organ:
        return "organs"
    if group == "dates":
        return "dates"
    return "requests"


def table_view_query_fields(querystring):
    fields = []
    for name, values in querystring.lists():
        if name in {"page", "group", "state_mode"}:
            continue
        fields.extend({"name": name, "value": value} for value in values)
    return fields


def row_count(rows):
    return len(rows) if isinstance(rows, list) else rows.count()
