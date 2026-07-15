from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit
from apps.directory.forms import TerritorialOrganPhotoFolderForm, TerritorialOrganPhotoForm
from apps.directory.models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder

from ..permissions import can_manage_photo_asset
from .photo_assets import (
    assign_photo_asset_author,
    can_upload_to_photo_folder,
    folder_tree_is_manageable,
    manageable_photo_folders_queryset,
    photo_folder_descendant_ids,
)
from .request_photos import photo_snapshot_for_audit


def photo_form_for_request(request, organ, photo=None):
    folder_queryset = manageable_photo_folders_queryset(request.user, organ)
    return TerritorialOrganPhotoForm(
        request.POST or None,
        request.FILES or None,
        instance=photo,
        organ=organ,
        folder_queryset=folder_queryset,
    )


def save_photo_asset(request, organ, photo, form, old_values=None):
    if photo and old_values is None:
        old_values = serialize_instance(photo)
    obj = form.save(commit=False)
    obj.territorial_organ = organ
    if photo and request.FILES.get("image"):
        obj.created_at = timezone.now()
    if not obj.pk:
        assign_photo_asset_author(obj, request.user)
    else:
        obj.updated_by = request.user
    obj.save()
    write_audit(
        AuditLog.Action.UPDATE if photo else AuditLog.Action.CREATE,
        obj,
        old_values=old_values,
        new_values=serialize_instance(obj),
        request=request,
    )
    return obj


def current_folder_for_form(request, organ, folder=None):
    parent_id = request.POST.get("parent") if request.method == "POST" else request.GET.get("folder")
    current_folder = folder.parent if folder else None
    if parent_id and not folder:
        current_folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=parent_id, territorial_organ=organ, is_deleted=False)
    return current_folder


def folder_form_for_request(request, organ, folder=None, current_folder=None):
    folder_queryset = manageable_photo_folders_queryset(request.user, organ)
    return TerritorialOrganPhotoFolderForm(
        request.POST or None,
        instance=folder,
        organ=organ,
        parent=current_folder,
        folder_queryset=folder_queryset,
    )


def save_photo_folder(request, organ, folder, form, current_folder, old_values=None):
    if folder and old_values is None:
        old_values = serialize_instance(folder)
    obj = form.save(commit=False)
    obj.territorial_organ = organ
    if not folder:
        obj.parent = current_folder
        assign_photo_asset_author(obj, request.user)
    elif "parent" not in request.POST:
        obj.parent = current_folder
        obj.updated_by = request.user
    else:
        obj.updated_by = request.user
    obj.save()
    new_values = serialize_instance(obj)
    if folder:
        folder_ids = photo_folder_descendant_ids(obj)
        active_photos = TerritorialOrganPhoto.objects.filter(
            territorial_organ=organ,
            folder_id__in=folder_ids,
            is_deleted=False,
        )
        new_values.update(photo_snapshot_for_audit(photos=active_photos))
    write_audit(
        AuditLog.Action.UPDATE if folder else AuditLog.Action.CREATE,
        obj,
        old_values=old_values,
        new_values=new_values,
        request=request,
    )
    return obj


def delete_photo_folder_tree(request, organ, folder):
    if not folder_tree_is_manageable(request.user, organ, folder):
        return False
    with transaction.atomic():
        old_values = serialize_instance(folder)
        folder_ids = photo_folder_descendant_ids(folder)
        photos = TerritorialOrganPhoto.objects.filter(
            territorial_organ=organ,
            folder_id__in=folder_ids,
            is_deleted=False,
        )
        old_values.update(photo_snapshot_for_audit(photos=photos))
        photos.update(
            is_deleted=True,
            updated_by=request.user,
            updated_at=timezone.now(),
        )
        TerritorialOrganPhotoFolder.objects.filter(
            territorial_organ=organ,
            pk__in=folder_ids,
        ).update(is_deleted=True, updated_by=request.user, updated_at=timezone.now())
        write_audit(AuditLog.Action.DELETE, folder, old_values=old_values, new_values=None, request=request)
    return True


def resolve_bulk_upload_folder(request, organ, current_folder):
    folder = None
    folder_created = False
    folder_id = request.POST.get("folder")
    if folder_id and current_folder is None:
        current_folder = get_object_or_404(TerritorialOrganPhotoFolder, pk=folder_id, territorial_organ=organ, is_deleted=False)
    if not can_upload_to_photo_folder(request.user, organ, current_folder):
        return None, current_folder, False, False

    new_folder_name = request.POST.get("new_folder", "").strip()
    if new_folder_name:
        folder = TerritorialOrganPhotoFolder.objects.filter(
            territorial_organ=organ,
            parent=current_folder,
            name=new_folder_name,
            is_deleted=False,
        ).first()
        if folder and not can_manage_photo_asset(request.user, organ, folder):
            return None, current_folder, False, False
        if folder is None:
            folder = TerritorialOrganPhotoFolder(territorial_organ=organ, parent=current_folder, name=new_folder_name)
            assign_photo_asset_author(folder, request.user)
            folder.save()
            folder_created = True
    elif folder_id:
        folder = current_folder
    return folder, current_folder, True, folder_created


BULK_PHOTO_BATCH_SIZE = 50


def _chunked(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def bulk_create_photos(request, organ, folder):
    files = request.FILES.getlist("images")
    descriptions = request.POST.getlist("descriptions")
    errors = []
    created = 0
    created_photo_ids = []
    folder_queryset = manageable_photo_folders_queryset(request.user, organ)
    # Batched in groups rather than one atomic() for all files (up to 500 per
    # request) or one per file - bounds how long a single transaction holds
    # the DB write lock while still cutting commit overhead well below
    # one-per-file.
    for batch in _chunked(enumerate(files), BULK_PHOTO_BATCH_SIZE):
        with transaction.atomic():
            for index, image in batch:
                data = {"description": descriptions[index] if index < len(descriptions) else ""}
                if folder:
                    data["folder"] = folder.pk
                form = TerritorialOrganPhotoForm(data, {"image": image}, organ=organ, folder_queryset=folder_queryset)
                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.territorial_organ = organ
                    assign_photo_asset_author(obj, request.user)
                    obj.save()
                    write_audit(AuditLog.Action.CREATE, obj, old_values=None, new_values=serialize_instance(obj), request=request)
                    created += 1
                    created_photo_ids.append(obj.pk)
                else:
                    errors.append(f"{image.name}: {form.errors.as_text()}")
    return created, errors, created_photo_ids


def soft_delete_photo(request, photo):
    old_values = serialize_instance(photo)
    photo.is_deleted = True
    photo.updated_by = request.user
    photo.save(update_fields=["is_deleted", "updated_by", "updated_at"])
    write_audit(AuditLog.Action.DELETE, photo, old_values=old_values, new_values=serialize_instance(photo), request=request)
    return photo
