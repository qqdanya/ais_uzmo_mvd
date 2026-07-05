from django.core.paginator import Paginator
from django.db.models import Count, Q

from apps.audit.models import AuditLog
from apps.audit.utils import write_audit
from apps.directory.models import TerritorialOrganPhoto

from ..models import RequestPhotoLink
from .request_numbers import request_content_type_for_model, request_content_type_for_object


REQUEST_PHOTO_PICKER_PAGE_SIZE = 12


def photo_matches_query(photo, query):
    query_normalized = query.casefold()
    return query_normalized in photo.description.casefold() or query_normalized in photo.original_filename.casefold()


def folder_path(folder):
    path = []
    while folder:
        if folder.is_deleted:
            return []
        path.append(folder)
        folder = folder.parent
    return list(reversed(path))


def folder_path_from_map(folder, folders_by_id):
    path = []
    while folder:
        if folder.is_deleted:
            return []
        path.append(folder)
        folder = folders_by_id.get(folder.parent_id)
    return list(reversed(path))


def add_folder_content_counts(organ, path):
    folder_ids = [folder.pk for folder in path]
    if not folder_ids:
        return path
    photo_counts = dict(
        organ.photos.filter(is_deleted=False, folder_id__in=folder_ids)
        .values("folder_id")
        .annotate(count=Count("id"))
        .values_list("folder_id", "count")
    )
    child_counts = dict(
        organ.photo_folders.filter(is_deleted=False, parent_id__in=folder_ids)
        .values("parent_id")
        .annotate(count=Count("id"))
        .values_list("parent_id", "count")
    )
    for folder in path:
        folder.breadcrumb_photo_count = photo_counts.get(folder.pk, 0)
        folder.breadcrumb_folder_count = child_counts.get(folder.pk, 0)
    return path


def available_request_photos(organ):
    return (
        organ.photos.select_related("folder", "created_by")
        .filter(is_deleted=False)
        .filter(Q(folder__isnull=True) | Q(folder__is_deleted=False))
        .order_by("-created_at", "-pk")
    )


def selected_request_photo_ids(instance):
    if not instance:
        return []
    content_type = request_content_type_for_object(instance)
    return list(
        RequestPhotoLink.objects.filter(
            territorial_organ=instance.territorial_organ,
            content_type=content_type,
            object_id=instance.pk,
            photo__is_deleted=False,
        )
        .filter(Q(photo__folder__isnull=True) | Q(photo__folder__is_deleted=False))
        .order_by("created_at", "id")
        .values_list("photo_id", flat=True)
    )


def request_photo_picker_context(request, organ, selected_ids):
    selected_ids = {int(value) for value in selected_ids if str(value).isdigit()}
    query = request.GET.get("photo_q", "").strip()
    folder_value = request.GET.get("photo_folder", "").strip()
    sort = request.GET.get("photo_sort", "newest")

    selected_folder = None
    if folder_value.isdigit():
        selected_folder = organ.photo_folders.filter(pk=folder_value, is_deleted=False).first()
        if selected_folder is None:
            folder_value = ""
    else:
        folder_value = ""

    child_folders = (
        organ.photo_folders.select_related("parent")
        .filter(parent=selected_folder, is_deleted=False)
        .annotate(
            photo_count=Count("photos", filter=Q(photos__is_deleted=False)),
            child_count=Count("children", filter=Q(children__is_deleted=False), distinct=True),
        )
        .order_by("name", "pk")
    )

    qs = available_request_photos(organ)
    if query and selected_folder is None:
        # Searching from the picker root should search the whole photo library,
        # including photos inside folders. Folder cards remain visible separately
        # so the user can also navigate the tree.
        scoped_qs = qs
    else:
        scoped_qs = qs.filter(folder=selected_folder) if selected_folder else qs.filter(folder__isnull=True)
    if query:
        query_normalized = query.casefold()
        qs = [
            photo
            for photo in scoped_qs
            if query_normalized in photo.description.casefold()
            or query_normalized in photo.original_filename.casefold()
            or (photo.folder and query_normalized in photo.folder.name.casefold())
        ]
        qs = sorted(qs, key=lambda photo: (photo.created_at, photo.pk), reverse=sort != "oldest")
    else:
        qs = scoped_qs.order_by("created_at", "pk") if sort == "oldest" else scoped_qs.order_by("-created_at", "-pk")

    page = Paginator(qs, REQUEST_PHOTO_PICKER_PAGE_SIZE).get_page(request.GET.get("photo_page"))
    photos = list(page.object_list)

    # Keep already selected photos visible even when the current folder/search filter
    # would otherwise hide them, so users can always see what remains attached.
    current_photo_ids = {photo.pk for photo in photos}
    selected_extra_photos = []
    if selected_ids:
        selected_extra_photos = list(
            available_request_photos(organ)
            .filter(pk__in=selected_ids)
            .exclude(pk__in=current_photo_ids)
            .order_by("-created_at", "-pk")
        )
    photos = selected_extra_photos + photos
    for photo in photos:
        photo.is_attached_to_request = photo.pk in selected_ids

    root_photo_count = organ.photos.filter(is_deleted=False, folder__isnull=True).count()
    root_folder_count = organ.photo_folders.filter(is_deleted=False, parent__isnull=True).count()
    folder_path_items = add_folder_content_counts(organ, folder_path(selected_folder))

    return {
        "available_photos": photos,
        "attached_photo_ids": selected_ids,
        "attached_photo_count": len(selected_ids),
        "photo_picker_page": page,
        "photo_picker_page_links": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "photo_picker_query": query,
        "photo_picker_folder": folder_value,
        "photo_picker_selected_folder": selected_folder,
        "photo_picker_folder_path": folder_path_items,
        "photo_picker_child_folders": child_folders,
        "photo_picker_root_photo_count": root_photo_count,
        "photo_picker_root_folder_count": root_folder_count,
        "photo_picker_sort": sort,
    }


def request_photo_form_context(request, organ, selected_ids):
    return request_photo_picker_context(request, organ, selected_ids)


def sync_request_photos(obj, photo_ids, user):
    selected_ids = {int(value) for value in photo_ids if str(value).isdigit()}
    content_type = request_content_type_for_object(obj)
    valid_photo_ids = set(available_request_photos(obj.territorial_organ).filter(pk__in=selected_ids).values_list("pk", flat=True))
    links = RequestPhotoLink.objects.filter(territorial_organ=obj.territorial_organ, content_type=content_type, object_id=obj.pk)
    existing_ids = set(links.values_list("photo_id", flat=True))
    removed_ids = existing_ids - valid_photo_ids
    links.exclude(photo_id__in=valid_photo_ids).delete()
    added_ids = valid_photo_ids - existing_ids
    RequestPhotoLink.objects.bulk_create(
        [
            RequestPhotoLink(
                territorial_organ=obj.territorial_organ,
                photo_id=photo_id,
                content_type=content_type,
                object_id=obj.pk,
                created_by=user,
            )
            for photo_id in added_ids
        ],
        ignore_conflicts=True,
    )
    return {"added": added_ids, "removed": removed_ids}


def photo_names_for_audit(photo_ids):
    if not photo_ids:
        return ""
    names = list(
        TerritorialOrganPhoto.objects.filter(pk__in=photo_ids)
        .order_by("original_filename", "pk")
        .values_list("original_filename", flat=True)
    )
    return ", ".join(name or "фотография" for name in names)


def write_request_photo_audit_events(obj, changes, request):
    added = changes.get("added") or set()
    removed = changes.get("removed") or set()
    if added:
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values={"photos": ""},
            new_values={"audit_event": "request_photos_attached", "photos": photo_names_for_audit(added)},
            request=request,
        )
    if removed:
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values={"photos": photo_names_for_audit(removed)},
            new_values={"audit_event": "request_photos_detached", "photos": ""},
            request=request,
        )


def attach_request_photo_counts(objects, model, organs):
    objects = list(objects)
    if not objects:
        return
    content_type = request_content_type_for_model(model)
    object_ids = [obj.pk for obj in objects]
    links = list(
        RequestPhotoLink.objects.select_related("photo", "photo__territorial_organ", "photo__created_by")
        .filter(
            territorial_organ__in=organs,
            content_type=content_type,
            object_id__in=object_ids,
            photo__is_deleted=False,
        )
        .filter(Q(photo__folder__isnull=True) | Q(photo__folder__is_deleted=False))
        .order_by("object_id", "created_at", "id")
    )
    counts = {}
    photos = {object_id: [] for object_id in object_ids}
    for link in links:
        counts[link.object_id] = counts.get(link.object_id, 0) + 1
        photos.setdefault(link.object_id, []).append(link.photo)
    for obj in objects:
        obj.attached_photo_count = counts.get(obj.pk, 0)
        obj.attached_photos = photos.get(obj.pk, [])
        obj.attached_photo_previews = obj.attached_photos[:3]
        obj.attached_photo_extra_count = max(obj.attached_photo_count - len(obj.attached_photo_previews), 0)
