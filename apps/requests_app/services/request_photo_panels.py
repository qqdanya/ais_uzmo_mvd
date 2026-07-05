from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from ..models import RequestPhotoLink
from ..permissions import can_view, can_write
from .downloads import download_ready_response, photos_zip_response, safe_download_name
from .http import toast_trigger
from .request_numbers import request_content_type_for_object
from .request_photos import (
    request_photo_form_context,
    request_photo_picker_context,
    sync_request_photos,
    write_request_photo_audit_events,
)
from ..registry import get_table_or_404
from .table_config import REQUEST_PHOTO_TABLES, REQUEST_TABLE_CONFIG


def request_object_or_404(organ, table_key, pk):
    model = REQUEST_TABLE_CONFIG[table_key]["model"]
    return get_object_or_404(model, pk=pk, territorial_organ=organ, is_deleted=False)


def request_photos_response(request, organ, table_key, pk):
    if table_key not in REQUEST_PHOTO_TABLES:
        raise Http404
    obj = request_object_or_404(organ, table_key, pk)
    if not can_view(request.user, organ):
        raise Http404
    department_slug = get_table_or_404(table_key)["department"]
    if request.method == "POST":
        if not can_write(request.user, organ, department_slug):
            raise Http404
        photo_changes = sync_request_photos(obj, request.POST.getlist("attached_photos"), request.user)
        write_request_photo_audit_events(obj, photo_changes, request)
    content_type = request_content_type_for_object(obj)
    links = (
        RequestPhotoLink.objects.select_related("photo", "photo__folder", "photo__created_by")
        .filter(territorial_organ=organ, content_type=content_type, object_id=obj.pk, photo__is_deleted=False)
        .filter(Q(photo__folder__isnull=True) | Q(photo__folder__is_deleted=False))
        .order_by("created_at", "id")
    )
    selected_ids = [link.photo_id for link in links]
    context = {
        "organ": organ,
        "object": obj,
        "table_key": table_key,
        "links": links,
        "can_write": can_write(request.user, organ, department_slug),
    }
    context.update(request_photo_form_context(request, organ, selected_ids))
    response = render(request, "partials/request_photos.html", context)
    if request.method == "POST":
        response["HX-Trigger"] = toast_trigger("Связанные фотографии обновлены.", requestPhotosChanged=True)
    return response


def request_photos_download_response(request, organ, table_key, pk):
    if table_key not in REQUEST_PHOTO_TABLES:
        raise Http404
    obj = request_object_or_404(organ, table_key, pk)
    if not can_view(request.user, organ):
        raise Http404
    content_type = request_content_type_for_object(obj)
    links = (
        RequestPhotoLink.objects.select_related("photo")
        .filter(territorial_organ=organ, content_type=content_type, object_id=obj.pk, photo__is_deleted=False)
        .filter(Q(photo__folder__isnull=True) | Q(photo__folder__is_deleted=False))
        .order_by("created_at", "id")
    )
    if not links.exists():
        raise Http404
    filename = safe_download_name(f"{obj}-photos.zip", f"request-{obj.pk}-photos.zip")
    return download_ready_response(request, photos_zip_response((link.photo for link in links), filename))


def request_photo_picker_response(request, organ):
    if not can_view(request.user, organ):
        raise Http404
    context = {"organ": organ}
    context.update(request_photo_picker_context(request, organ, request.GET.getlist("attached_photos")))
    return render(request, "partials/request_photo_picker_panel.html", context)
