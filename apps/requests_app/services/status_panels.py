from django.http import Http404
from django.shortcuts import get_object_or_404, render

from ..forms import QuickStatusUpdateForm
from ..permissions import can_view, can_write
from .http import htmx_triggers
from .record_actions import update_record_status
from .statuses import completed_date_field, status_history_queryset
from .table_config import REQUEST_TABLE_CONFIG, STATUS_HISTORY_TABLES


def status_history_response(request, organ, table_key, pk):
    if table_key not in STATUS_HISTORY_TABLES:
        raise Http404
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
        },
    )


def status_update_response(request, organ, table_key, table, pk, refresh_table):
    if table_key not in STATUS_HISTORY_TABLES or not can_write(request.user, organ, table["department"]):
        raise Http404

    obj = get_object_or_404(table["model"], pk=pk, territorial_organ=organ, is_deleted=False)
    completion_field = completed_date_field(table_key)
    form = QuickStatusUpdateForm(
        request.POST or None,
        current_status=obj.status,
        current_completed_at=getattr(obj, completion_field),
    )

    if request.method == "POST" and form.is_valid():
        update_record_status(
            request,
            obj,
            table_key,
            form.cleaned_data["status"],
            form.cleaned_data["completed_at"],
        )
        response = refresh_table()
        response["HX-Trigger"] = htmx_triggers("Статус заявки изменён.")
        return response

    response = render(
        request,
        "partials/quick_status_form.html",
        {
            "form": form,
            "object": obj,
            "organ": organ,
            "table": table,
        },
    )
    if request.method == "POST":
        response["HX-Retarget"] = "#modal-content"
    return response
