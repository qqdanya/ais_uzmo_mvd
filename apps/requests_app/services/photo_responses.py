import mimetypes

from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.directory.models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder

from ..permissions import can_manage_photo_asset, can_view, can_write
from .downloads import download_ready_response, photo_download_name, photos_zip_response, safe_download_name
from .http import htmx_triggers
from .photo_asset_actions import (
    bulk_create_photos,
    current_folder_for_form,
    delete_photo_folder_tree,
    folder_form_for_request,
    photo_form_for_request,
    resolve_bulk_upload_folder,
    save_photo_asset,
    save_photo_folder,
    soft_delete_photo,
)
from .photo_assets import can_upload_to_photo_folder, photo_folder_descendant_ids, photo_gallery_context
from .request_photos import folder_path_from_map


def render_photos(request, organ, folder_id_override=None):
    return render(request, "partials/photos.html", photo_gallery_context(request, organ, request.user, folder_id_override))


def photo_download_response(request, organ, pk):
    if not can_view(request.user, organ):
        raise Http404
    photo = get_object_or_404(
        TerritorialOrganPhoto.objects.filter(Q(folder__isnull=True) | Q(folder__is_deleted=False)),
        pk=pk,
        territorial_organ=organ,
        is_deleted=False,
    )
    if not photo.image:
        raise Http404
    try:
        file_handle = photo.image.open("rb")
    except FileNotFoundError:
        raise Http404
    filename = photo_download_name(photo)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(file_handle, as_attachment=True, filename=filename, content_type=content_type)


def photos_download_all_response(request, organ):
    if not can_view(request.user, organ):
        raise Http404
    photos_qs = organ.photos.filter(is_deleted=False).filter(Q(folder__isnull=True) | Q(folder__is_deleted=False)).order_by("created_at")
    if not photos_qs.exists():
        raise Http404
    filename = safe_download_name(f"{organ.name}-photos.zip", f"organ-{organ.pk}-photos.zip")
    return download_ready_response(request, photos_zip_response(photos_qs, filename))


def photo_folder_download_response(request, organ, pk):
    if not can_view(request.user, organ):
        raise Http404
    folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=pk, territorial_organ=organ, is_deleted=False)
    folder_ids = photo_folder_descendant_ids(folder)
    photos_qs = (
        organ.photos.select_related("folder")
        .filter(is_deleted=False, folder_id__in=folder_ids)
        .filter(folder__is_deleted=False)
        .order_by("folder_id", "created_at", "pk")
    )
    if not photos_qs.exists():
        raise Http404
    folders_by_id = {item.pk: item for item in organ.photo_folders.filter(pk__in=folder_ids, is_deleted=False)}
    root_index = folder_path_from_map(folder, folders_by_id)

    def archive_path(photo, source_name):
        current_path = folder_path_from_map(photo.folder, folders_by_id)
        nested_path = current_path[len(root_index):]
        parts = [safe_download_name(item.name, f"folder-{item.pk}") for item in nested_path]
        return "/".join([*parts, source_name]) if parts else source_name

    filename = safe_download_name(f"{folder.name}-photos.zip", f"folder-{folder.pk}-photos.zip")
    return download_ready_response(request, photos_zip_response(photos_qs, filename, archive_path))


def photo_form_response(request, organ, pk=None):
    if not can_write(request.user, organ):
        raise Http404
    photo = get_object_or_404(TerritorialOrganPhoto, pk=pk, territorial_organ=organ) if pk else None
    if photo and not can_manage_photo_asset(request.user, organ, photo):
        raise Http404
    form = photo_form_for_request(request, organ, photo)
    if request.method == "POST" and form.is_valid():
        obj = save_photo_asset(request, organ, photo, form)
        response = render_photos(request, organ, obj.folder_id or "")
        response["HX-Trigger"] = htmx_triggers("Фотография сохранена.")
        return response
    return render(request, "partials/photo_form.html", {"form": form, "organ": organ, "photo": photo})


def photo_folder_form_response(request, organ, pk=None):
    if not can_write(request.user, organ):
        raise Http404
    folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=pk, territorial_organ=organ, is_deleted=False) if pk else None
    if folder and not can_manage_photo_asset(request.user, organ, folder):
        raise Http404
    current_folder = current_folder_for_form(request, organ, folder)
    if not can_upload_to_photo_folder(request.user, organ, current_folder):
        raise Http404
    form = folder_form_for_request(request, organ, folder, current_folder)
    if request.method == "POST" and form.is_valid():
        obj = save_photo_folder(request, organ, folder, form, current_folder)
        response = render_photos(request, organ, obj.parent_id or "")
        response["HX-Trigger"] = htmx_triggers("Папка переименована." if folder else "Папка создана.")
        return response
    return render(request, "partials/photo_folder_form.html", {"form": form, "organ": organ, "folder": folder, "current_folder": current_folder})


def photo_folder_delete_response(request, organ, pk):
    folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=pk, territorial_organ=organ, is_deleted=False)
    if not can_manage_photo_asset(request.user, organ, folder):
        raise Http404
    parent = folder.parent
    if request.method == "POST":
        if not delete_photo_folder_tree(request, organ, folder):
            raise Http404
        response = render_photos(request, organ, parent.pk if parent else "")
        response["HX-Trigger"] = htmx_triggers("Папка удалена.")
        return response
    return render(request, "partials/confirm_delete.html", {"object": folder, "organ": organ, "folder_delete": True})


def photo_bulk_upload_response(request, organ):
    if not can_write(request.user, organ):
        raise Http404
    current_folder = None
    if request.GET.get("folder"):
        current_folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=request.GET["folder"], territorial_organ=organ, is_deleted=False)
    if not can_upload_to_photo_folder(request.user, organ, current_folder):
        raise Http404
    if request.method == "POST":
        folder, current_folder, allowed = resolve_bulk_upload_folder(request, organ, current_folder)
        if not allowed:
            raise Http404
        created, errors = bulk_create_photos(request, organ, folder)
        if request.headers.get("X-Bulk-Photo-Batch") == "true":
            return JsonResponse(
                {
                    "created": created,
                    "failed": len(errors),
                    "errors": errors[:10],
                    "folder": folder.pk if folder else None,
                }
            )
        response = render_photos(request, organ, folder.pk if folder else "")
        if errors:
            response["HX-Trigger"] = htmx_triggers(f"Загружено: {created}. Не загружено: {len(errors)}.", "warning")
        else:
            response["HX-Trigger"] = htmx_triggers(f"Фотографий загружено: {created}.")
        return response
    return render(request, "partials/photo_bulk_form.html", {"organ": organ, "current_folder": current_folder})


def photo_delete_response(request, organ, pk):
    photo = get_object_or_404(TerritorialOrganPhoto, pk=pk, territorial_organ=organ)
    if not can_manage_photo_asset(request.user, organ, photo):
        raise Http404
    if request.method == "POST":
        soft_delete_photo(request, photo)
        response = render_photos(request, organ, photo.folder_id or "")
        response["HX-Trigger"] = htmx_triggers("Фотография удалена.")
        return response
    return render(request, "partials/confirm_delete.html", {"object": photo, "organ": organ, "photo_delete": True})
