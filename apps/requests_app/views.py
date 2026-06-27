import csv
import json
import mimetypes
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Min, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import capfirst
from django.views.decorators.http import require_http_methods
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit
from apps.directory.forms import TerritorialOrganPhotoFolderForm, TerritorialOrganPhotoForm
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder

from .forms import TmcRequestForm, form_for_table
from .models import (
    AntiTerrorMeasure,
    BuildingRepairRequest,
    CitsiziEquipment,
    FireDepartmentRequest,
    NeedStatus,
    RequestStatusHistory,
    TmcRequest,
    VehicleRepairRequest,
)
from .permissions import can_view, can_write
from .registry import TABLES, TABLE_BY_KEY


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def active_organs():
    return TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).prefetch_related("children")


def photo_matches_query(photo, query):
    query_normalized = query.casefold()
    return query_normalized in photo.description.casefold() or query_normalized in photo.original_filename.casefold()


@login_required
def dashboard(request):
    organs = active_organs()
    departments = Department.objects.filter(is_active=True)
    selected_organ = organs.first()
    selected_department = departments.first()
    return render(request, "dashboard/index.html", {"organs": organs, "departments": departments, "selected_organ": selected_organ, "selected_department": selected_department, "tables": TABLES})


@login_required
def organ_info(request, pk):
    organ = get_object_or_404(TerritorialOrgan.objects.prefetch_related("children"), pk=pk, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    return render(request, "partials/organ_info.html", {"organ": organ})


@login_required
def department_tables(request, organ_id, department_slug):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    department = get_object_or_404(Department, slug=department_slug, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    table = TABLES[department.slug][0]
    return render(request, "partials/tables_panel.html", {"organ": organ, "department": department, "tables": TABLES[department.slug], "active_table": table})


def filtered_queryset(request, table, organ):
    qs = table["model"].objects.select_related("territorial_organ", "created_by", "updated_by").filter(territorial_organ=organ, is_deleted=False)
    if table["key"] in REQUEST_TABLE_CONFIG:
        return request_table_queryset(request, table["key"], organ, include_status=True)
    if request.GET.get("equipment_type") and hasattr(table["model"], "equipment_type"):
        qs = qs.filter(equipment_type=request.GET["equipment_type"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    return qs


def request_date_filter_values(request, model, organ):
    oldest_date = model.objects.filter(territorial_organ=organ, is_deleted=False).aggregate(oldest=Min("request_date")).get("oldest")
    date_from = request.GET.get("date_from") if "date_from" in request.GET else (oldest_date.isoformat() if oldest_date else "")
    date_to = request.GET.get("date_to") if "date_to" in request.GET else timezone.localdate().isoformat()
    return {"date_from": date_from, "date_to": date_to}


def request_table_date_filter_values(request, table_key, organ):
    return request_date_filter_values(request, REQUEST_TABLE_CONFIG[table_key]["model"], organ)


def request_table_queryset(request, table_key, organ, include_status=False):
    config = REQUEST_TABLE_CONFIG[table_key]
    qs = config["model"].objects.select_related("territorial_organ", "created_by", "updated_by")
    if config.get("prefetch"):
        qs = qs.prefetch_related(*config["prefetch"])
    qs = qs.filter(territorial_organ=organ, is_deleted=False)

    query = request.GET.get("q", "").strip()
    if query:
        search_q = Q()
        for field_name in config["search_fields"]:
            search_q |= Q(**{f"{field_name}__icontains": query})
        qs = qs.filter(search_q)
        if config.get("distinct_search"):
            qs = qs.distinct()

    date_filters = request_table_date_filter_values(request, table_key, organ)
    date_from = parse_date(date_filters["date_from"])
    date_to = parse_date(date_filters["date_to"])
    if date_from:
        qs = qs.filter(request_date__gte=date_from)
    if date_to:
        qs = qs.filter(request_date__lte=date_to)
    if include_status and request.GET.get("status") in NeedStatus.values:
        qs = qs.filter(status=request.GET["status"])
    if config.get("equipment_type_filter") and valid_equipment_type(request.GET.get("equipment_type")):
        qs = qs.filter(equipment_type=request.GET["equipment_type"])
    return qs


def request_status_stats(qs):
    return {
        "new_count": qs.filter(status=NeedStatus.NEW).count(),
        "in_work_count": qs.filter(status=NeedStatus.IN_WORK).count(),
        "done_count": qs.filter(status=NeedStatus.DONE).count(),
        "rejected_count": qs.filter(status=NeedStatus.REJECTED).count(),
    }


def valid_equipment_type(value):
    return value in {choice[0] for choice in CitsiziEquipment._meta.get_field("equipment_type").choices}


STATUS_HISTORY_TABLES = {
    "tmc-requests",
    "anti-terror",
    "building-repair",
    "citsizi-equipment",
    "vehicle-repair",
    "fire-requests",
}


COMPLETED_DATE_FIELDS = {
    "citsizi-equipment": "due_date",
    "tmc-requests": "due_date",
}


REQUEST_TABLE_CONFIG = {
    "tmc-requests": {
        "model": TmcRequest,
        "search_fields": ("request_number", "comment", "items__name"),
        "prefetch": ("items",),
        "distinct_search": True,
        "completed_label": "Дата исполнения",
    },
    "vehicle-repair": {
        "model": VehicleRepairRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения заявки",
    },
    "fire-requests": {
        "model": FireDepartmentRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения заявки",
    },
    "anti-terror": {
        "model": AntiTerrorMeasure,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения заявки",
    },
    "citsizi-equipment": {
        "model": CitsiziEquipment,
        "search_fields": ("request_number", "comment"),
        "equipment_type_filter": True,
        "completed_label": "Дата исполнения заявки",
    },
    "building-repair": {
        "model": BuildingRepairRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения заявки",
    },
}


XLSX_EXPORT_CONFIG = {
    "vehicle-inventory": {
        "widths": {
            "state_date": 14,
            "required_count": 14,
            "available_count": 14,
            "broken_count": 16,
            "writeoff_count": 38,
        },
        "center_columns": {"state_date", "required_count", "available_count", "broken_count", "writeoff_count"},
    },
    "vehicle-repair": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
    "fire-extinguishers": {
        "widths": {
            "state_date": 14,
            "required_count": 14,
            "available_count": 14,
            "expiry_date": 24,
            "writeoff_count": 18,
        },
        "center_columns": {"state_date", "required_count", "available_count", "expiry_date", "writeoff_count"},
    },
    "fire-alarm": {
        "widths": {
            "state_date": 14,
            "required_objects": 28,
            "equipped_objects": 26,
            "broken_objects": 28,
        },
        "center_columns": {"state_date", "required_objects", "equipped_objects", "broken_objects"},
    },
    "security-alarm": {
        "widths": {
            "state_date": 14,
            "required_objects": 28,
            "equipped_objects": 26,
            "broken_objects": 28,
        },
        "center_columns": {"state_date", "required_objects", "equipped_objects", "broken_objects"},
    },
    "fire-requests": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
    "anti-terror": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
    "citsizi-equipment": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "quantity": 14,
            "status": 22,
            "equipment_type": 28,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "quantity", "status", "equipment_type"},
    },
    "service-housing": {
        "widths": {
            "state_date": 14,
            "total_count": 18,
            "used_by_staff": 24,
            "ready_to_move": 20,
        },
        "center_columns": {"state_date", "total_count", "used_by_staff", "ready_to_move"},
    },
    "building-repair": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
}


def completed_date_field(table_key):
    return COMPLETED_DATE_FIELDS.get(table_key, "completed_at")


def status_history_content_type(obj):
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def status_history_queryset(obj):
    return RequestStatusHistory.objects.select_related("changed_by").filter(content_type=status_history_content_type(obj), object_id=obj.pk)


def create_status_history(obj, old_status, new_status, completed_at, changed_by, note):
    return RequestStatusHistory.objects.create(
        content_type=status_history_content_type(obj),
        object_id=obj.pk,
        old_status=old_status,
        new_status=new_status,
        completed_at=completed_at,
        changed_by=changed_by,
        note=note,
    )


def display_fields(table):
    field_names = table["fields"]
    fields_by_name = {field.name: field for field in table["model"]._meta.fields}
    computed_labels = {"items_summary": "наименования"}
    return [fields_by_name.get(name) or SimpleNamespace(name=name, verbose_name=computed_labels.get(name, name)) for name in field_names]


def table_header_labels(fields):
    return [capfirst(field.verbose_name) for field in fields]


def export_cell_value(obj, field):
    display = getattr(obj, f"get_{field.name}_display", None)
    value = display() if callable(display) else getattr(obj, field.name)
    if hasattr(value, "strftime") and getattr(field, "get_internal_type", lambda: "")() == "DateField":
        return value.strftime("%d.%m.%Y")
    return value


@login_required
def table_data(request, organ_id, table_key):
    table = TABLE_BY_KEY[table_key]
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    table_stats = {}
    table_filters = {}
    qs = filtered_queryset(request, table, organ)
    is_request_table = table_key in REQUEST_TABLE_CONFIG
    if is_request_table:
        table_filters = request_table_date_filter_values(request, table_key, organ)
        stats_qs = request_table_queryset(request, table_key, organ)
        table_stats = request_status_stats(stats_qs)
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))
    querystring = request.GET.copy()
    querystring.pop("page", None)
    return render(
        request,
        "partials/table_data.html",
        {
            "organ": organ,
            "table": table,
            "fields": display_fields(table),
            "page": page,
            "can_write": can_write(request.user, organ),
            "table_querystring": querystring.urlencode(),
            "status_choices": NeedStatus.choices,
            "table_stats": table_stats,
            "table_filters": table_filters,
            "is_request_table": is_request_table,
            "has_status_history": table_key in STATUS_HISTORY_TABLES,
            "search_placeholder": "Поиск по заявке и ТМЦ" if table_key == "tmc-requests" else "Поиск по заявке и комментарию",
            "equipment_type_choices": CitsiziEquipment._meta.get_field("equipment_type").choices,
        },
    )


def htmx_triggers(message, level="success"):
    return json.dumps({"modal:close": True, "toast": {"message": message, "level": level}})


def tmc_item_rows_from_request(request):
    rows = []
    errors = []
    names = request.POST.getlist("item_name")
    quantities = request.POST.getlist("item_quantity")
    units = request.POST.getlist("item_unit")
    for index, name in enumerate(names):
        name = name.strip()
        quantity_raw = quantities[index].strip() if index < len(quantities) else ""
        unit = units[index].strip() if index < len(units) else "шт."
        if not name and not quantity_raw:
            continue
        row = {"name": name, "quantity": quantity_raw, "unit": unit or "шт."}
        if not name:
            errors.append("Укажите наименование в каждой заполненной позиции.")
        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                raise ValueError
            row["quantity"] = quantity
        except (TypeError, ValueError):
            errors.append(f"Укажите положительное количество для позиции «{name or 'без наименования'}».")
        rows.append(row)
    if not rows:
        errors.append("Добавьте хотя бы одну позицию заявки.")
    return rows, errors


def tmc_item_rows_from_instance(instance):
    if not instance:
        return [{"name": "", "quantity": "", "unit": "шт."}]
    return [{"name": item.name, "quantity": item.quantity, "unit": item.unit} for item in instance.items.all()] or [{"name": "", "quantity": "", "unit": "шт."}]


def tmc_snapshot(instance):
    data = serialize_instance(instance)
    data["items"] = "; ".join(str(item) for item in instance.items.all())
    return data


def tmc_record_form(request, organ, table, instance=None):
    old_values = tmc_snapshot(instance) if instance else None
    old_status = instance.status if instance else None
    form = TmcRequestForm(request.POST or None, instance=instance)
    item_rows = tmc_item_rows_from_instance(instance)
    item_errors = []
    if request.method == "POST":
        item_rows, item_errors = tmc_item_rows_from_request(request)
        if form.is_valid() and not item_errors:
            is_create = instance is None
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.territorial_organ = organ
                if not obj.pk:
                    obj.created_by = request.user
                obj.updated_by = request.user
                obj.save()
                obj.items.all().delete()
                for row in item_rows:
                    obj.items.create(name=row["name"], quantity=row["quantity"], unit=row["unit"])
                if is_create or old_status != obj.status:
                    create_status_history(
                        obj=obj,
                        old_status=None if is_create else old_status,
                        new_status=obj.status,
                        completed_at=obj.due_date if obj.status == NeedStatus.DONE else None,
                        changed_by=request.user,
                        note="Создание заявки" if is_create else "Изменение статуса",
                    )
            write_audit(AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE, obj, old_values=old_values, new_values=tmc_snapshot(obj), request=request)
            response = table_data(request, organ.pk, table["key"])
            response["HX-Trigger"] = htmx_triggers("Заявка сохранена.")
            return response
    return render(request, "partials/tmc_request_form.html", {"form": form, "organ": organ, "table": table, "instance": instance, "item_rows": item_rows, "item_errors": item_errors})


@login_required
def status_history(request, organ_id, table_key, pk):
    if table_key not in STATUS_HISTORY_TABLES:
        raise Http404
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    model = REQUEST_TABLE_CONFIG[table_key]["model"]
    obj = get_object_or_404(model, pk=pk, territorial_organ=organ, is_deleted=False)
    if not can_view(request.user, organ):
        raise Http404
    return render(
        request,
        "partials/status_history.html",
        {
            "organ": organ,
            "object": obj,
            "history": status_history_queryset(obj),
            "completed_label": REQUEST_TABLE_CONFIG[table_key]["completed_label"],
        },
    )


def tmc_xlsx_response(qs, organ, filename):
    wb = Workbook()
    ws = wb.active
    ws.title = "Заявки ТМЦ"

    ws.merge_cells("A1:B1")
    ws.merge_cells("C1:E1")
    ws.merge_cells("F1:F2")
    ws["A1"] = "Сведения о потребности ТМЦ"
    ws["C1"] = "Заявка"
    ws["F1"] = "Комментарий"
    headers = ["Наименование", "Количество", "Номер", "Дата", "Исполнение заявки", ""]
    for column, value in enumerate(headers, start=1):
        if value:
            ws.cell(row=2, column=column, value=value)

    widths = {
        "A": 34,
        "B": 16,
        "C": 18,
        "D": 14,
        "E": 22,
        "F": 34,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    ws.freeze_panes = "A3"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    thin = Side(style="thin", color="C6DBE9")
    block = Side(style="medium", color="7FAED0")
    header_bottom = Side(style="medium", color="8FBFDD")
    header_fill = PatternFill("solid", fgColor="D6EAF7")
    subheader_fill = PatternFill("solid", fgColor="E5F1FA")
    header_font = Font(bold=True, color="0B2F5B")
    body_alignment = Alignment(vertical="top", wrap_text=True)
    center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in range(1, 3):
        for column in range(1, 7):
            cell = ws.cell(row=row, column=column)
            cell.fill = header_fill if row == 1 else subheader_fill
            cell.font = header_font
            cell.alignment = center_alignment
            cell.border = Border(
                left=thin,
                right=block if column in {2, 5, 6} else thin,
                top=thin,
                bottom=header_bottom if row == 2 else thin,
            )

    current_row = 3
    requests = list(qs)
    for request_index, obj in enumerate(requests):
        items = list(obj.items.all()) or [None]
        start_row = current_row
        end_row = current_row + len(items) - 1

        for item in items:
            ws.cell(row=current_row, column=1, value=item.name if item else "-")
            ws.cell(row=current_row, column=2, value=f"{item.quantity} {item.unit}" if item else "-")
            current_row += 1

        ws.cell(row=start_row, column=3, value=obj.request_number)
        ws.cell(row=start_row, column=4, value=obj.request_date.strftime("%d.%m.%Y"))
        ws.cell(row=start_row, column=5, value=obj.get_status_display())
        ws.cell(row=start_row, column=6, value=obj.comment)

        if end_row > start_row:
            for column in range(3, 7):
                ws.merge_cells(start_row=start_row, start_column=column, end_row=end_row, end_column=column)

        is_last_request = request_index == len(requests) - 1
        for row in range(start_row, end_row + 1):
            for column in range(1, 7):
                cell = ws.cell(row=row, column=column)
                cell.alignment = center_alignment if column in {3, 4, 5} else body_alignment
                cell.border = Border(
                    left=thin,
                    right=block if column in {2, 5, 6} else thin,
                    top=thin,
                    bottom=thin if is_last_request else block,
                )

    if current_row > 3:
        ws.auto_filter.ref = f"A2:F{current_row - 1}"

    buffer = BytesIO()
    wb.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def styled_xlsx_response(qs, table, fields, filename, widths=None, center_columns=None):
    wb = Workbook()
    ws = wb.active
    ws.title = table["title"][:31]
    headers = table_header_labels(fields)
    ws.append(headers)

    widths = widths or {}
    for index, field in enumerate(fields, start=1):
        column = ws.cell(row=1, column=index).column_letter
        ws.column_dimensions[column].width = widths.get(field.name, 18)

    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    thin = Side(style="thin", color="C6DBE9")
    block = Side(style="medium", color="7FAED0")
    header_bottom = Side(style="medium", color="8FBFDD")
    header_fill = PatternFill("solid", fgColor="D6EAF7")
    header_font = Font(bold=True, color="0B2F5B")
    body_alignment = Alignment(vertical="top", wrap_text=True)
    center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    center_columns = center_columns or set()
    last_column = len(fields)

    for column in range(1, last_column + 1):
        cell = ws.cell(row=1, column=column)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_alignment
        cell.border = Border(left=thin, right=block if column == last_column else thin, top=thin, bottom=header_bottom)

    for row_index, obj in enumerate(qs, start=2):
        for column, field in enumerate(fields, start=1):
            cell = ws.cell(row=row_index, column=column, value=export_cell_value(obj, field))
            cell.alignment = center_alignment if field.name in center_columns else body_alignment
            cell.border = Border(left=thin, right=block if column == last_column else thin, top=thin, bottom=thin)

    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=last_column).column_letter}{ws.max_row}"

    buffer = BytesIO()
    wb.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def record_form(request, organ_id, table_key, pk=None):
    table = TABLE_BY_KEY[table_key]
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_write(request.user, organ):
        raise Http404
    instance = get_object_or_404(table["model"], pk=pk, territorial_organ=organ) if pk else None
    if table_key == "tmc-requests":
        return tmc_record_form(request, organ, table, instance)
    Form = form_for_table(table_key)
    old_values = serialize_instance(instance) if instance else None
    old_status = instance.status if instance and table_key in STATUS_HISTORY_TABLES else None
    form = Form(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        is_create = instance is None
        obj = form.save(commit=False)
        obj.territorial_organ = organ
        completion_field = completed_date_field(table_key)
        if table_key in STATUS_HISTORY_TABLES and obj.status == NeedStatus.DONE and not getattr(obj, completion_field):
            setattr(obj, completion_field, timezone.localdate())
        if not obj.pk:
            obj.created_by = request.user
        obj.updated_by = request.user
        obj.save()
        if table_key in STATUS_HISTORY_TABLES and (is_create or old_status != obj.status):
            create_status_history(
                obj=obj,
                old_status=None if is_create else old_status,
                new_status=obj.status,
                completed_at=getattr(obj, completion_field) if obj.status == NeedStatus.DONE else None,
                changed_by=request.user,
                note="Создание заявки" if is_create else "Изменение статуса",
            )
        write_audit(AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE, obj, old_values=old_values, new_values=serialize_instance(obj), request=request)
        response = table_data(request, organ.pk, table_key)
        response["HX-Trigger"] = htmx_triggers("Запись сохранена.")
        return response
    return render(request, "partials/record_form.html", {"form": form, "organ": organ, "table": table, "instance": instance})


@login_required
@require_http_methods(["GET", "POST"])
def record_delete(request, organ_id, table_key, pk):
    table = TABLE_BY_KEY[table_key]
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    obj = get_object_or_404(table["model"], pk=pk, territorial_organ=organ)
    if not can_write(request.user, organ):
        raise Http404
    if request.method == "POST":
        old_values = serialize_instance(obj)
        obj.is_deleted = True
        obj.updated_by = request.user
        obj.save(update_fields=["is_deleted", "updated_by", "updated_at"])
        write_audit(AuditLog.Action.DELETE, obj, old_values=old_values, new_values=serialize_instance(obj), request=request)
        response = table_data(request, organ.pk, table_key)
        response["HX-Trigger"] = htmx_triggers("Запись удалена.")
        return response
    return render(request, "partials/confirm_delete.html", {"object": obj, "organ": organ, "table": table})


@login_required
def export_table(request, organ_id, table_key, fmt):
    table = TABLE_BY_KEY[table_key]
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id)
    if not can_view(request.user, organ):
        raise Http404
    qs = filtered_queryset(request, table, organ)
    fields = display_fields(table)
    filename = f"{table_key}-{organ.pk}.{fmt}"
    if fmt == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(table_header_labels(fields))
        for obj in qs:
            writer.writerow([getattr(obj, f"get_{f.name}_display", lambda: getattr(obj, f.name))() for f in fields])
        return response
    if fmt == "xlsx":
        if table_key == "tmc-requests":
            return tmc_xlsx_response(qs, organ, filename)
        if table_key in XLSX_EXPORT_CONFIG:
            return styled_xlsx_response(qs, table, fields, filename, **XLSX_EXPORT_CONFIG[table_key])
        wb = Workbook()
        ws = wb.active
        ws.title = table["title"][:31]
        ws.append(table_header_labels(fields))
        for obj in qs:
            ws.append([str(getattr(obj, f"get_{f.name}_display", lambda: getattr(obj, f.name))()) for f in fields])
        buffer = BytesIO()
        wb.save(buffer)
        response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    raise Http404


@login_required
def photos(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "newest")
    folder_id = request.GET.get("folder", "").strip()
    selected_folder = None
    if folder_id:
        selected_folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=folder_id, territorial_organ=organ)
    folders = organ.photo_folders.annotate(photo_count=Count("photos", filter=Q(photos__is_deleted=False)))
    if query and not folder_id:
        query_normalized = query.casefold()
        folders = [folder for folder in folders if query_normalized in folder.name.casefold()]
    qs = organ.photos.select_related("created_by", "folder").filter(is_deleted=False)
    if folder_id:
        qs = qs.filter(folder_id=folder_id)
    if query:
        qs = [photo for photo in qs if photo_matches_query(photo, query)]
        qs = sorted(qs, key=lambda photo: (photo.created_at, photo.pk), reverse=sort != "oldest")
    else:
        qs = qs.order_by("created_at", "pk") if sort == "oldest" else qs.order_by("-created_at", "-pk")
    paginator = Paginator(qs, 24)
    page = paginator.get_page(request.GET.get("page"))
    querystring = request.GET.copy()
    querystring.pop("page", None)
    return render(
        request,
        "partials/photos.html",
        {
            "organ": organ,
            "photos": page.object_list,
            "photo_page": page,
            "photo_querystring": querystring.urlencode(),
            "folders": folders,
            "selected_folder": selected_folder,
            "photo_folder": folder_id,
            "can_write": can_write(request.user, organ),
            "photo_query": query,
            "photo_sort": sort,
        },
    )


def safe_download_name(value, fallback):
    name = "".join(char if char.isalnum() or char in "._- " else "_" for char in value).strip()
    return name or fallback


@login_required
def photo_download(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    photo = get_object_or_404(TerritorialOrganPhoto, pk=pk, territorial_organ=organ, is_deleted=False)
    if not photo.image:
        raise Http404
    try:
        file_handle = photo.image.open("rb")
    except FileNotFoundError:
        raise Http404
    filename = safe_download_name(Path(photo.image.name).name, f"photo-{photo.pk}")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(file_handle, as_attachment=True, filename=filename, content_type=content_type)


@login_required
def photos_download_all(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    photos_qs = organ.photos.filter(is_deleted=False).order_by("created_at")
    if not photos_qs.exists():
        raise Http404
    archive = BytesIO()
    used_names = set()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for index, photo in enumerate(photos_qs, start=1):
            if not photo.image:
                continue
            source_name = safe_download_name(Path(photo.image.name).name, f"photo-{photo.pk}")
            stem = Path(source_name).stem
            suffix = Path(source_name).suffix
            archive_name = source_name
            if archive_name in used_names:
                archive_name = f"{stem}-{photo.pk}{suffix}"
            used_names.add(archive_name)
            try:
                with photo.image.open("rb") as file_handle:
                    zip_file.writestr(f"{index:03d}-{archive_name}", file_handle.read())
            except FileNotFoundError:
                continue
    archive.seek(0)
    filename = safe_download_name(f"{organ.name}-photos.zip", f"organ-{organ.pk}-photos.zip")
    return FileResponse(archive, as_attachment=True, filename=filename, content_type="application/zip")


@login_required
@require_http_methods(["GET", "POST"])
def photo_form(request, organ_id, pk=None):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_write(request.user, organ):
        raise Http404
    photo = get_object_or_404(TerritorialOrganPhoto, pk=pk, territorial_organ=organ) if pk else None
    old_values = serialize_instance(photo) if photo else None
    form = TerritorialOrganPhotoForm(request.POST or None, request.FILES or None, instance=photo, organ=organ)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.territorial_organ = organ
        if not obj.pk:
            obj.created_by = request.user
        obj.updated_by = request.user
        obj.save()
        write_audit(AuditLog.Action.UPDATE if photo else AuditLog.Action.CREATE, obj, old_values=old_values, new_values=serialize_instance(obj), request=request)
        response = photos(request, organ.pk)
        response["HX-Trigger"] = htmx_triggers("Фотография сохранена.")
        return response
    return render(request, "partials/photo_form.html", {"form": form, "organ": organ, "photo": photo})


@login_required
@require_http_methods(["GET", "POST"])
def photo_folder_form(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_write(request.user, organ):
        raise Http404
    form = TerritorialOrganPhotoFolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        folder = form.save(commit=False)
        folder.territorial_organ = organ
        folder.save()
        response = photos(request, organ.pk)
        response["HX-Trigger"] = htmx_triggers("Папка создана.")
        return response
    return render(request, "partials/photo_folder_form.html", {"form": form, "organ": organ})


@login_required
@require_http_methods(["GET", "POST"])
def photo_bulk_upload(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_write(request.user, organ):
        raise Http404
    current_folder = None
    if request.GET.get("folder"):
        current_folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=request.GET["folder"], territorial_organ=organ)
    if request.method == "POST":
        files = request.FILES.getlist("images")
        descriptions = request.POST.getlist("descriptions")
        folder = None
        folder_id = request.POST.get("folder")
        new_folder_name = request.POST.get("new_folder", "").strip()
        if new_folder_name:
            folder, _ = TerritorialOrganPhotoFolder.objects.get_or_create(territorial_organ=organ, name=new_folder_name)
        elif folder_id:
            folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=folder_id, territorial_organ=organ)
        errors = []
        created = 0
        for index, image in enumerate(files):
            data = {"description": descriptions[index] if index < len(descriptions) else ""}
            if folder:
                data["folder"] = folder.pk
            form = TerritorialOrganPhotoForm(data, {"image": image}, organ=organ)
            if form.is_valid():
                obj = form.save(commit=False)
                obj.territorial_organ = organ
                obj.created_by = request.user
                obj.updated_by = request.user
                obj.save()
                write_audit(AuditLog.Action.CREATE, obj, old_values=None, new_values=serialize_instance(obj), request=request)
                created += 1
            else:
                errors.append(f"{image.name}: {form.errors.as_text()}")
        response = photos(request, organ.pk)
        if errors:
            response["HX-Trigger"] = htmx_triggers(f"Загружено: {created}. Не загружено: {len(errors)}.", "warning")
        else:
            response["HX-Trigger"] = htmx_triggers(f"Фотографий загружено: {created}.")
        return response
    return render(request, "partials/photo_bulk_form.html", {"organ": organ, "current_folder": current_folder})


@login_required
@require_http_methods(["GET", "POST"])
def photo_delete(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    photo = get_object_or_404(TerritorialOrganPhoto, pk=pk, territorial_organ=organ)
    if not can_write(request.user, organ):
        raise Http404
    if request.method == "POST":
        old_values = serialize_instance(photo)
        photo.is_deleted = True
        photo.updated_by = request.user
        photo.save(update_fields=["is_deleted", "updated_by", "updated_at"])
        write_audit(AuditLog.Action.DELETE, photo, old_values=old_values, new_values=serialize_instance(photo), request=request)
        response = photos(request, organ.pk)
        response["HX-Trigger"] = htmx_triggers("Фотография удалена.")
        return response
    return render(request, "partials/confirm_delete.html", {"object": photo, "organ": organ, "photo_delete": True})
