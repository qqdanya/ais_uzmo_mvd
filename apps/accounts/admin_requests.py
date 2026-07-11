from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count, IntegerField, Q, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department
from apps.requests_app.models import NeedStatus, RequestPhotoLink, RequestStatusHistory
from apps.requests_app.permissions import can_view
from apps.requests_app.registry import TABLE_BY_KEY

from .admin_summary import available_organs_for_user, request_tables, selected_organs
from .admin_common import (
    DEFAULT_PER_PAGE,
    DEPARTMENT_ICONS,
    STATUS_BADGE_CLASSES,
    apply_period,
    completion_totals_for_queryset,
    date_period_from_request,
    days_class,
    department_options,
    field_label,
    field_value,
    multiselect_label,
    processing_caption,
    processing_days,
    query_with,
    request_number,
    request_title,
    selected_values,
)
from .business_days import subtract_business_days_inclusive
from .admin_thresholds import get_request_stale_workdays


STATUS_FILTERS = {
    "all": "Все",
    "in_work": "В работе",
    "done": "Исполнено",
    "rejected": "Отклонено",
    "stale": "Зависшие",
}
REQUEST_LIST_ORDERING = ("-request_date", "-created_at", "-pk")
REQUEST_DETAIL_REQUIRED_FIELDS = {"status", "request_date", "territorial_organ", "is_deleted"}


def selected_departments(request, options):
    return selected_values(request, "department", [item["slug"] for item in options])


def selected_states(request):
    return selected_values(request, "state", STATUS_FILTERS.keys())


def department_name_map():
    return {item.slug: item.name for item in Department.objects.filter(is_active=True)}


def stale_cutoff_date():
    return subtract_business_days_inclusive(timezone.localdate(), get_request_stale_workdays() + 1)


def base_table_queryset(table, organs):
    return table["model"].objects.select_related("territorial_organ").filter(is_deleted=False, territorial_organ__in=organs)


def apply_search(qs, query):
    query = (query or "").strip()
    if not query:
        return qs
    filters = Q(request_number__icontains=query) | Q(comment__icontains=query) | Q(territorial_organ__name__icontains=query)
    return qs.filter(filters).distinct()


def apply_state(qs, states):
    states = [state for state in (states or []) if state != "all"]
    if not states:
        return qs
    query = Q()
    if "in_work" in states:
        query |= Q(status=NeedStatus.IN_WORK)
    if "done" in states:
        query |= Q(status=NeedStatus.DONE)
    if "rejected" in states:
        query |= Q(status=NeedStatus.REJECTED)
    if "stale" in states:
        query |= Q(status=NeedStatus.IN_WORK, request_date__lte=stale_cutoff_date())
    return qs.filter(query) if query else qs


def table_matches_departments(table, filters):
    departments = filters.get("departments") or []
    return not departments or table["department"] in departments


def matching_tables(tables, filters):
    return [table for table in tables if table_matches_departments(table, filters)]


def filtered_queryset(table, organs, filters, *, with_state=True):
    qs = base_table_queryset(table, organs)
    qs = apply_period(qs, filters["period"])
    qs = apply_search(qs, filters["query"])
    if with_state:
        qs = apply_state(qs, filters.get("states") or [])
    return qs


def table_status_counts(table, organs, filters, stale_before):
    return filtered_queryset(table, organs, filters, with_state=False).aggregate(
        all=Count("pk"),
        in_work=Count("pk", filter=Q(status=NeedStatus.IN_WORK)),
        done=Count("pk", filter=Q(status=NeedStatus.DONE)),
        rejected=Count("pk", filter=Q(status=NeedStatus.REJECTED)),
        stale=Count("pk", filter=Q(status=NeedStatus.IN_WORK, request_date__lte=stale_before)),
    )


def status_counts(tables, organs, filters):
    counts = {key: 0 for key in STATUS_FILTERS}
    stale_before = stale_cutoff_date()
    for table in matching_tables(tables, filters):
        table_counts = table_status_counts(table, organs, filters, stale_before)
        for key in counts:
            counts[key] += table_counts.get(key) or 0
    return counts


def request_row(table, obj, departments):
    days = processing_days(obj)
    return {
        "id": obj.pk,
        "table_key": table["key"],
        "number": request_number(obj),
        "request_date": obj.request_date,
        "request_date_display": obj.request_date.strftime("%d.%m.%Y") if obj.request_date else "—",
        "organ": obj.territorial_organ.name,
        "organ_id": obj.territorial_organ_id,
        "department_slug": table["department"],
        "department": departments.get(table["department"], table["department"]),
        "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
        "request_type": request_title(table, obj),
        "status": obj.status,
        "status_label": obj.get_status_display(),
        "status_class": STATUS_BADGE_CLASSES.get(obj.status, ""),
        "days": days,
        "has_days": days is not None,
        "days_class": days_class(days),
        "days_caption": processing_caption(obj, days),
        "detail_url": reverse("admin_request_detail", kwargs={"table_key": table["key"], "pk": obj.pk}),
    }


def request_index_count(tables, organs, filters):
    return sum(filtered_queryset(table, organs, filters).count() for table in matching_tables(tables, filters))


def request_index_queryset(table, organs, filters, table_order):
    return (
        filtered_queryset(table, organs, filters)
        .order_by()
        .annotate(
            row_request_date=Coalesce("request_date", Value(date.min)),
            row_pk=Coalesce("pk", Value(0), output_field=IntegerField()),
            row_table_key=Value(table["key"]),
            row_table_order=Value(table_order, output_field=IntegerField()),
        )
        .values_list("row_request_date", "row_pk", "row_table_key", "row_table_order")
    )


def request_row_index_page(tables, organs, filters, offset, per_page):
    if per_page <= 0:
        return []
    indexed_parts = [
        request_index_queryset(table, organs, filters, table_order)
        for table_order, table in enumerate(matching_tables(tables, filters))
    ]
    if not indexed_parts:
        return []
    union_qs = indexed_parts[0].union(*indexed_parts[1:], all=True).order_by("-row_request_date", "-row_pk", "row_table_order")
    return [(request_date, pk, table_key) for request_date, pk, table_key, _ in union_qs[offset:offset + per_page]]


def hydrate_request_rows(tables_by_key, index_rows):
    """Build full display rows for a (page-sized) slice of request_row_index()."""
    departments = department_name_map()
    pks_by_table = {}
    for _, pk, table_key in index_rows:
        pks_by_table.setdefault(table_key, []).append(pk)

    objects_by_table = {}
    for table_key, pks in pks_by_table.items():
        table = tables_by_key[table_key]
        qs = table["model"].objects.select_related("territorial_organ").filter(pk__in=pks)
        objects = list(qs)
        attach_processing_end_dates(table, objects)
        objects_by_table[table_key] = {obj.pk: obj for obj in objects}

    rows = []
    for _, pk, table_key in index_rows:
        obj = objects_by_table[table_key].get(pk)
        if obj:
            rows.append(request_row(tables_by_key[table_key], obj, departments))
    return rows


def own_completion_date(obj):
    for field_name in ("completed_at", "due_date"):
        value = getattr(obj, field_name, None)
        if value:
            return value
    return None


def latest_history_dates(content_type, object_ids, status):
    if not object_ids:
        return {}
    order_by = ("object_id", "-completed_at", "-changed_at", "-pk") if status == NeedStatus.DONE else ("object_id", "-changed_at", "-pk")
    rows = RequestStatusHistory.objects.filter(
        content_type=content_type,
        object_id__in=object_ids,
        new_status=status,
    ).order_by(*order_by)
    dates = {}
    for history in rows:
        if history.object_id in dates:
            continue
        dates[history.object_id] = history.completed_at or history.changed_at.date()
    return dates


def attach_processing_end_dates(table, objects):
    content_type = ContentType.objects.get_for_model(table["model"], for_concrete_model=False)
    done_missing_ids = []
    rejected_ids = []
    for obj in objects:
        if obj.status == NeedStatus.DONE:
            own_date = own_completion_date(obj)
            if own_date:
                obj._processing_end_date = own_date
            else:
                done_missing_ids.append(obj.pk)
        elif obj.status == NeedStatus.REJECTED:
            rejected_ids.append(obj.pk)

    done_dates = latest_history_dates(content_type, done_missing_ids, NeedStatus.DONE)
    rejected_dates = latest_history_dates(content_type, rejected_ids, NeedStatus.REJECTED)
    for obj in objects:
        if obj.status == NeedStatus.DONE and not hasattr(obj, "_processing_end_date"):
            obj._processing_end_date = done_dates.get(obj.pk)
        elif obj.status == NeedStatus.REJECTED:
            obj._processing_end_date = rejected_dates.get(obj.pk)


def average_completion_days(tables, organs, filters):
    total_days = 0
    total_count = 0
    for table in matching_tables(tables, filters):
        qs = filtered_queryset(table, organs, filters, with_state=False)
        table_days, table_count = completion_totals_for_queryset(qs, table["key"])
        total_days += table_days
        total_count += table_count
    if not total_count:
        return None
    return round(total_days / total_count, 1)


def request_kpis(counts, avg_completion_days):
    return [
        {"label": "В работе", "value": counts.get("in_work", 0), "hint": "текущие заявки", "icon": "bi-hourglass-split"},
        {"label": "Исполнено", "value": counts.get("done", 0), "hint": "по текущим фильтрам", "icon": "bi-check2-circle"},
        {
            "label": "Средний срок исполнения",
            "value": f"{str(avg_completion_days).replace('.', ',')} дн." if avg_completion_days is not None else "—",
            "hint": "по исполненным заявкам",
            "icon": "bi-stopwatch",
        },
        {"label": "Зависшие", "value": counts.get("stale", 0), "hint": f"в работе более {get_request_stale_workdays()} рабочих дней", "icon": "bi-exclamation-triangle"},
    ]


def active_filter_chips(filters, selected_organs_list, available_organs, departments):
    chips = []
    if filters["period"]["date_from"] or filters["period"]["date_to"]:
        chips.append(f"Период: {filters['period']['label']}")
    if len(selected_organs_list) != len(available_organs):
        if len(selected_organs_list) == 1:
            chips.append(f"Орган: {selected_organs_list[0].name}")
        else:
            chips.append(f"Органы: {len(selected_organs_list)} из {len(available_organs)}")
    if filters.get("departments"):
        names = {item["slug"]: item["name"] for item in departments}
        chips.append(f"Отделы: {multiselect_label(filters['departments'], 'Все отделы', names)}")
    if filters["query"]:
        chips.append(f"Поиск: {filters['query']}")
    if filters.get("states"):
        chips.append(f"Статусы: {multiselect_label(filters['states'], 'Все статусы', STATUS_FILTERS)}")
    return chips


def pagination_fields(request):
    fields = []
    for name in ("date_from", "date_to", "q"):
        value = request.GET.get(name, "")
        if value:
            fields.append({"name": name, "value": value})
    for name in ("department", "state", "organ_ids"):
        for value in request.GET.getlist(name):
            if value:
                fields.append({"name": name, "value": value})
    if request.GET.get("organ_filter_empty") == "1":
        fields.append({"name": "organ_filter_empty", "value": "1"})
    return fields


def build_request_filters(request, departments):
    filters = {
        "period": date_period_from_request(request),
        "departments": selected_departments(request, departments),
        "states": selected_states(request),
        "department": "",
        "state": "all",
        "query": (request.GET.get("q", "") or "").strip(),
        "per_page": DEFAULT_PER_PAGE,
    }
    filters["department"] = filters["departments"][0] if len(filters["departments"]) == 1 else ""
    filters["state"] = filters["states"][0] if len(filters["states"]) == 1 else "all"
    return filters


def build_status_tabs(request, counts, filters):
    return [
        {
            "key": key,
            "label": label,
            "count": counts.get(key, 0),
            "url": f"?{query_with(request, state=key)}",
            "active": (not filters["states"] and key == "all") or filters["states"] == [key],
        }
        for key, label in STATUS_FILTERS.items()
    ]


def paginate_request_index(request, tables, organs, filters, per_page):
    total_count = request_index_count(tables, organs, filters)
    paginator = Paginator(range(total_count), per_page)
    page = paginator.get_page(request.GET.get("page"))
    offset = page.start_index() - 1 if total_count else 0
    index_rows = request_row_index_page(tables, organs, filters, offset, per_page)
    tables_by_key = {table["key"]: table for table in tables}
    page.object_list = hydrate_request_rows(tables_by_key, index_rows)
    return page, page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)


def build_requests_context(request):
    tables = list(request_tables())
    available_organs = available_organs_for_user(request.user)
    organs = selected_organs(request, available_organs)
    departments = department_options(tables)
    filters = build_request_filters(request, departments)
    counts = status_counts(tables, organs, filters)
    avg_completion = average_completion_days(tables, organs, filters)
    page, page_links = paginate_request_index(request, tables, organs, filters, filters["per_page"])
    selected_ids = {organ.pk for organ in organs}
    department_labels = {item["slug"]: item["name"] for item in departments}
    return {
        "active_tab": "requests",
        "organs": available_organs,
        "selected_organs": organs,
        "selected_organ_ids": selected_ids,
        "all_organs_selected": len(organs) == len(available_organs),
        "departments": departments,
        "filters": filters,
        "status_tabs": build_status_tabs(request, counts, filters),
        "status_options": [(key, label) for key, label in STATUS_FILTERS.items() if key != "all"],
        "department_label": multiselect_label(filters["departments"], "Все отделы", department_labels),
        "state_label": multiselect_label(filters["states"], "Все статусы", STATUS_FILTERS),
        "request_kpis": request_kpis(counts, avg_completion),
        "page": page,
        "page_links": page_links,
        "total_count": page.paginator.count,
        "querystring": query_with(request),
        "pagination_url": reverse("admin_requests_panel"),
        "pagination_fields": pagination_fields(request),
        "active_filter_chips": active_filter_chips(filters, organs, available_organs, departments),
        "reset_url": reverse("admin_requests_panel"),
    }


def table_field_names(model):
    return {field.name for field in model._meta.fields}


def table_for_detail(table_key):
    table = TABLE_BY_KEY.get(table_key)
    if not table:
        return None
    if not REQUEST_DETAIL_REQUIRED_FIELDS.issubset(table_field_names(table["model"])):
        return None
    return table


def build_detail_fields(table, obj):
    return [{"label": field_label(table, name), "value": field_value(obj, name)} for name in table.get("fields", [])]


def build_request_detail_context(request, table_key, pk):
    table = table_for_detail(table_key)
    if not table:
        raise Http404
    show_deleted = request.GET.get("deleted") == "1"
    obj = get_object_or_404(
        table["model"].objects.select_related("territorial_organ", "created_by", "updated_by"),
        pk=pk,
        is_deleted=show_deleted,
    )
    if not can_view(request.user, obj.territorial_organ):
        raise Http404
    departments = department_name_map()
    content_type = ContentType.objects.get_for_model(table["model"], for_concrete_model=False)
    history = RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk).select_related("changed_by")[:8]
    photo_links = list(
        RequestPhotoLink.objects.select_related("photo", "photo__territorial_organ", "photo__created_by")
        .filter(content_type=content_type, object_id=obj.pk, photo__is_deleted=False)
        .filter(Q(photo__folder__isnull=True) | Q(photo__folder__is_deleted=False))
        .order_by("created_at", "id")
    )
    attached_photos = [link.photo for link in photo_links if link.photo and link.photo.image]
    photo_count = len(attached_photos)
    days = processing_days(obj)
    return {
        "active_tab": "trash" if show_deleted else "requests",
        "table": table,
        "object": obj,
        "request_number": request_number(obj),
        "request_title": request_title(table, obj),
        "department_name": departments.get(table["department"], table["department"]),
        "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
        "status_class": STATUS_BADGE_CLASSES.get(obj.status, ""),
        "days": days,
        "has_days": days is not None,
        "days_class": days_class(days),
        "days_caption": processing_caption(obj, days),
        "fields": build_detail_fields(table, obj),
        "history": history,
        "photo_count": photo_count,
        "attached_photos": attached_photos,
        "back_url": request.META.get("HTTP_REFERER") or (reverse("admin_trash_panel") + "?section=requests" if show_deleted else reverse("admin_requests_panel")),
        "is_deleted_detail": show_deleted,
        "edit_url": "" if show_deleted else reverse("record_update", kwargs={"organ_id": obj.territorial_organ_id, "table_key": table_key, "pk": obj.pk}),
    }
