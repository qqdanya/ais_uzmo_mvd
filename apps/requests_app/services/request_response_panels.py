from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from apps.audit.models import AuditLog
from apps.audit.utils import write_audit

from ..forms import REQUEST_RESPONSE_DUPLICATE_MESSAGE, RequestResponseForm
from ..models import RequestResponse
from ..permissions import can_view, can_write
from ..registry import get_table_or_404
from .http import toast_trigger
from .request_photo_panels import request_object_or_404
from .request_responses import (
    request_response_audit_snapshot,
    request_response_content_type,
    request_response_queryset,
)
from .table_config import REQUEST_TABLE_CONFIG


def response_object_or_404(request_object, response_pk):
    return get_object_or_404(
        RequestResponse,
        pk=response_pk,
        content_type=request_response_content_type(request_object),
        object_id=request_object.pk,
    )


def response_panel_context(request, organ, table_key, request_object, form=None):
    table = get_table_or_404(table_key)
    writable = can_write(request.user, organ, table["department"])
    responses = list(request_response_queryset(request_object))
    if form is None and writable:
        form = RequestResponseForm(request_object=request_object)
    return {
        "organ": organ,
        "table": table,
        "table_key": table_key,
        "object": request_object,
        "responses": responses,
        "response_count": len(responses),
        "can_write": writable,
        "form": form,
        "return_to_status": request.GET.get("return_to") == "status",
    }


def render_response_panel(request, organ, table_key, request_object, form=None):
    return render(
        request,
        "partials/request_responses.html",
        response_panel_context(request, organ, table_key, request_object, form),
    )


def write_response_audit(request, request_object, response, event_type, *, old_values=None, deleted=False):
    snapshot = request_response_audit_snapshot(response)
    new_values = {"audit_event": event_type}
    if not deleted:
        new_values.update(snapshot)
    write_audit(
        AuditLog.Action.UPDATE,
        request_object,
        old_values=old_values,
        new_values=new_values,
        request=request,
        event_type=event_type,
    )


def request_responses_response(request, organ, table_key, pk):
    if table_key not in REQUEST_TABLE_CONFIG:
        raise Http404
    request_object = request_object_or_404(organ, table_key, pk)
    if not can_view(request.user, organ):
        raise Http404

    table = get_table_or_404(table_key)
    writable = can_write(request.user, organ, table["department"])
    form = None
    saved = False
    if request.method == "POST":
        if not writable:
            raise Http404
        form = RequestResponseForm(request.POST, request_object=request_object)
        if form.is_valid():
            try:
                with transaction.atomic():
                    response_object = form.save(commit=False)
                    response_object.content_type = request_response_content_type(request_object)
                    response_object.object_id = request_object.pk
                    response_object.created_by = request.user
                    response_object.updated_by = request.user
                    response_object.save()
                    write_response_audit(
                        request,
                        request_object,
                        response_object,
                        AuditLog.EventType.RESPONSE_CREATED,
                    )
                request.session.modified = True
                saved = True
                form = None
            except IntegrityError:
                form.add_error("response_number", REQUEST_RESPONSE_DUPLICATE_MESSAGE)

    response = render_response_panel(request, organ, table_key, request_object, form)
    if saved:
        response["HX-Trigger"] = toast_trigger(
            "Ответ добавлен. Статус заявки не изменён.",
            requestResponsesChanged=True,
        )
    return response


def request_response_update_response(request, organ, table_key, pk, response_pk):
    if table_key not in REQUEST_TABLE_CONFIG:
        raise Http404
    table = get_table_or_404(table_key)
    if not can_write(request.user, organ, table["department"]):
        raise Http404
    request_object = request_object_or_404(organ, table_key, pk)
    response_object = response_object_or_404(request_object, response_pk)
    old_values = request_response_audit_snapshot(response_object)
    form = RequestResponseForm(
        request.POST or None,
        instance=response_object,
        request_object=request_object,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                stored = RequestResponse.objects.select_for_update().get(pk=response_object.pk)
                old_values = request_response_audit_snapshot(stored)
                for field_name in ("response_number", "response_date", "note"):
                    setattr(stored, field_name, form.cleaned_data[field_name])
                stored.updated_by = request.user
                stored.save()
                write_response_audit(
                    request,
                    request_object,
                    stored,
                    AuditLog.EventType.RESPONSE_UPDATED,
                    old_values=old_values,
                )
            request.session.modified = True
            response = render_response_panel(request, organ, table_key, request_object)
            response["HX-Trigger"] = toast_trigger(
                "Ответ изменён. Статус заявки не изменён.",
                requestResponsesChanged=True,
            )
            return response
        except IntegrityError:
            form.add_error("response_number", REQUEST_RESPONSE_DUPLICATE_MESSAGE)

    return render(
        request,
        "partials/request_response_form.html",
        {
            "organ": organ,
            "table": table,
            "table_key": table_key,
            "object": request_object,
            "response_object": response_object,
            "form": form,
            "return_to_status": request.GET.get("return_to") == "status",
        },
    )


def request_response_delete_response(request, organ, table_key, pk, response_pk):
    if table_key not in REQUEST_TABLE_CONFIG:
        raise Http404
    table = get_table_or_404(table_key)
    if not can_write(request.user, organ, table["department"]):
        raise Http404
    request_object = request_object_or_404(organ, table_key, pk)
    response_object = response_object_or_404(request_object, response_pk)

    if request.method == "POST":
        with transaction.atomic():
            stored = RequestResponse.objects.select_for_update().get(pk=response_object.pk)
            old_values = request_response_audit_snapshot(stored)
            stored.delete()
            write_response_audit(
                request,
                request_object,
                response_object,
                AuditLog.EventType.RESPONSE_DELETED,
                old_values=old_values,
                deleted=True,
            )
        request.session.modified = True
        response = render_response_panel(request, organ, table_key, request_object)
        response["HX-Trigger"] = toast_trigger(
            "Ответ удалён. Статус заявки не изменён.",
            requestResponsesChanged=True,
        )
        return response

    return render(
        request,
        "partials/request_response_confirm_delete.html",
        {
            "organ": organ,
            "table": table,
            "table_key": table_key,
            "object": request_object,
            "response_object": response_object,
            "return_to_status": request.GET.get("return_to") == "status",
        },
    )
