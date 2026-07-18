from django.http import Http404
from django.shortcuts import get_object_or_404, render

from ..permissions import can_view
from .statuses import status_history_queryset
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
