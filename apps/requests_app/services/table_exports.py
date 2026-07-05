from django.http import Http404

from .downloads import csv_file_response, download_ready_response
from .exports import (
    basic_xlsx_response,
    display_fields,
    grouped_export_headers,
    grouped_export_row,
    request_grouped_xlsx_response,
    styled_xlsx_response,
    table_header_labels,
    tmc_grouped_xlsx_response,
    tmc_xlsx_response,
)
from .grouping import (
    request_date_grouped_rows,
    request_group_mode,
    request_organ_grouped_rows,
    tmc_date_grouped_rows,
    tmc_grouped_rows,
    tmc_organ_grouped_rows,
)
from .table_config import REQUEST_TABLE_CONFIG, XLSX_EXPORT_CONFIG
from .table_filters import STATE_SNAPSHOT_TABLES, filtered_queryset, fire_extinguisher_filtered_queryset, state_snapshot_queryset


def export_table_response(request, organ, table, table_key, fmt, selected_organs):
    """Build a CSV/XLSX response for the current table view."""
    qs = filtered_queryset(request, table, selected_organs)
    fields = display_fields(table)
    filename = f"{table_key}-{organ.pk}.{fmt}"
    is_multi_organ = len(selected_organs) > 1
    is_request_table = table_key in REQUEST_TABLE_CONFIG
    is_fire_extinguisher_table = table_key == "fire-extinguishers"

    if table_key in STATE_SNAPSHOT_TABLES:
        qs = state_snapshot_queryset(request, table_key, qs)
    if is_fire_extinguisher_table:
        qs = fire_extinguisher_filtered_queryset(request, qs)

    current_group_mode = request_group_mode(request, table_key, is_multi_organ) if is_request_table else "requests"
    if current_group_mode in {"products", "organs", "dates"}:
        is_tmc = table_key == "tmc-requests"
        if current_group_mode == "organs":
            rows = list(tmc_organ_grouped_rows(qs) if is_tmc else request_organ_grouped_rows(qs))
        elif current_group_mode == "dates":
            rows = list(tmc_date_grouped_rows(qs) if is_tmc else request_date_grouped_rows(qs))
        else:
            rows = list(tmc_grouped_rows(qs))

        if fmt == "csv":
            csv_rows = [grouped_export_headers(current_group_mode, is_tmc=is_tmc, is_multi_organ=is_multi_organ)]
            csv_rows.extend(grouped_export_row(row, current_group_mode, is_tmc=is_tmc, is_multi_organ=is_multi_organ) for row in rows)
            return download_ready_response(request, csv_file_response(filename, csv_rows))
        if fmt == "xlsx":
            if is_tmc:
                return download_ready_response(request, tmc_grouped_xlsx_response(rows, is_multi_organ, filename, current_group_mode))
            return download_ready_response(request, request_grouped_xlsx_response(rows, table, filename, current_group_mode))

    if fmt == "csv":
        csv_rows = [table_header_labels(fields)]
        for obj in qs:
            csv_rows.append([getattr(obj, f"get_{f.name}_display", lambda: getattr(obj, f.name))() for f in fields])
        return download_ready_response(request, csv_file_response(filename, csv_rows))

    if fmt == "xlsx":
        if table_key == "tmc-requests":
            return download_ready_response(request, tmc_xlsx_response(qs, organ, filename, len(selected_organs) > 1))
        if table_key in XLSX_EXPORT_CONFIG:
            return download_ready_response(request, styled_xlsx_response(qs, table, fields, filename, **XLSX_EXPORT_CONFIG[table_key]))
        return download_ready_response(request, basic_xlsx_response(qs, table, fields, filename))

    raise Http404
