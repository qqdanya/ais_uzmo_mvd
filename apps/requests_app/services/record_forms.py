from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from ..forms import TmcRequestForm, form_for_table
from ..permissions import can_write
from .http import htmx_triggers
from .request_numbers import REQUEST_NUMBER_DUPLICATE_MESSAGE, validate_request_number
from .request_photos import request_photo_form_context, selected_request_photo_ids
from .record_actions import save_record, save_tmc_record, soft_delete_record
from .table_config import REQUEST_PHOTO_TABLES, STATUS_HISTORY_TABLES
from .tmc import tmc_item_rows_from_instance, tmc_item_rows_from_request


def tmc_record_form_response(request, organ, table, instance, refresh_table):
    if not can_write(request.user, organ, table["department"]):
        raise Http404
    form = TmcRequestForm(request.POST or None, instance=instance)
    item_rows = tmc_item_rows_from_instance(instance)
    item_errors = []
    selected_photo_ids = request.POST.getlist("attached_photos") if request.method == "POST" else selected_request_photo_ids(instance)
    if request.method == "POST":
        item_rows, item_errors = tmc_item_rows_from_request(request)
        form_is_valid = form.is_valid()
        number_is_valid = validate_request_number(form, organ, table, instance) if form_is_valid else False
        if form_is_valid and number_is_valid and not item_errors:
            try:
                save_tmc_record(request, organ, table, instance, form, item_rows)
                # Marking the session modified re-saves it and pushes its expiry
                # SESSION_COOKIE_AGE forward, so active users aren't logged out
                # mid-week even though SESSION_SAVE_EVERY_REQUEST is off.
                request.session.modified = True
                response = refresh_table()
                response["HX-Trigger"] = htmx_triggers("Заявка сохранена.")
                return response
            except IntegrityError:
                form.add_error("request_number", REQUEST_NUMBER_DUPLICATE_MESSAGE)
    context = {
        "form": form,
        "organ": organ,
        "table": table,
        "instance": instance,
        "item_rows": item_rows,
        "item_errors": item_errors,
        "show_request_photo_picker": True,
    }
    context.update(request_photo_form_context(request, organ, selected_photo_ids))
    response = render(request, "partials/tmc_request_form.html", context)
    if request.method == "POST":
        response["HX-Retarget"] = "#modal-content"
    return response


def record_form_response(request, organ, table_key, table, instance, refresh_table):
    if not can_write(request.user, organ, table["department"]):
        raise Http404
    if table_key == "tmc-requests":
        return tmc_record_form_response(request, organ, table, instance, refresh_table)

    Form = form_for_table(table_key)
    form = Form(request.POST or None, instance=instance)
    selected_photo_ids = request.POST.getlist("attached_photos") if request.method == "POST" else selected_request_photo_ids(instance)
    if request.method == "POST":
        form_is_valid = form.is_valid()
        number_is_valid = validate_request_number(form, organ, table, instance) if form_is_valid else False
        if form_is_valid and number_is_valid:
            try:
                save_record(
                    request,
                    organ,
                    table,
                    table_key,
                    instance,
                    form,
                    selected_photo_ids,
                    REQUEST_PHOTO_TABLES,
                    STATUS_HISTORY_TABLES,
                )
                # See tmc_record_form_response above: extends the session on
                # save instead of on every request.
                request.session.modified = True
                response = refresh_table()
                response["HX-Trigger"] = htmx_triggers("Запись сохранена.")
                return response
            except IntegrityError:
                form.add_error("request_number", REQUEST_NUMBER_DUPLICATE_MESSAGE)

    context = {
        "form": form,
        "organ": organ,
        "table": table,
        "instance": instance,
        "show_request_photo_picker": table_key in REQUEST_PHOTO_TABLES,
    }
    if table_key in REQUEST_PHOTO_TABLES:
        context.update(request_photo_form_context(request, organ, selected_photo_ids))
    response = render(request, "partials/record_form.html", context)
    if request.method == "POST":
        response["HX-Retarget"] = "#modal-content"
    return response


def record_delete_response(request, organ, table_key, table, pk, refresh_table):
    obj = get_object_or_404(table["model"], pk=pk, territorial_organ=organ)
    if not can_write(request.user, organ, table["department"]):
        raise Http404
    if request.method == "POST":
        soft_delete_record(request, obj)
        response = refresh_table()
        response["HX-Trigger"] = htmx_triggers("Запись перемещена в корзину.")
        return response
    return render(request, "partials/confirm_delete.html", {"object": obj, "organ": organ, "table": table})
