from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from apps.requests_app.services.table_filters import search_query_variants

from apps.directory.models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder

from ..permissions import can_manage_photo_asset, can_write, user_primary_department
from .request_photos import add_folder_content_counts, folder_path, folder_path_from_map, photo_search_q


PHOTO_GALLERY_PAGE_SIZE = 24


def add_photo_asset_permissions(user, organ, folders, photos):
    for folder in folders:
        folder.can_manage = can_manage_photo_asset(user, organ, folder)
    for photo in photos:
        photo.can_manage = can_manage_photo_asset(user, organ, photo)


def manageable_photo_folders_queryset(user, organ):
    folders = list(organ.photo_folders.select_related("parent", "created_by", "created_department").filter(is_deleted=False))
    folder_ids = [folder.pk for folder in folders if can_manage_photo_asset(user, organ, folder)]
    return organ.photo_folders.select_related("parent").filter(pk__in=folder_ids, is_deleted=False)


def can_upload_to_photo_folder(user, organ, folder):
    return can_write(user, organ) and (folder is None or can_manage_photo_asset(user, organ, folder))


def assign_photo_asset_author(obj, user):
    obj.created_by = user
    obj.updated_by = user
    obj.created_department = user_primary_department(user)


def photo_folder_descendant_ids(folder):
    folder_ids = [folder.pk]
    pending = [folder.pk]
    while pending:
        child_ids = list(TerritorialOrganPhotoFolder.objects.filter(parent_id__in=pending, is_deleted=False).values_list("pk", flat=True))
        folder_ids.extend(child_ids)
        pending = child_ids
    return folder_ids


def folder_tree_is_manageable(user, organ, folder):
    folder_ids = photo_folder_descendant_ids(folder)
    folders = organ.photo_folders.filter(pk__in=folder_ids, is_deleted=False)
    photos = organ.photos.filter(folder_id__in=folder_ids, is_deleted=False)
    return all(can_manage_photo_asset(user, organ, item) for item in folders) and all(can_manage_photo_asset(user, organ, item) for item in photos)


def selected_photo_folder(organ, folder_id):
    if not folder_id:
        return None
    return get_object_or_404(TerritorialOrganPhotoFolder, pk=folder_id, territorial_organ=organ, is_deleted=False)


def gallery_folders_queryset(organ, selected_folder, sort, query):
    folders = organ.photo_folders.select_related("created_by", "created_department").filter(parent=selected_folder, is_deleted=False).annotate(
        photo_count=Count("photos", filter=Q(photos__is_deleted=False)),
        child_count=Count("children", filter=Q(children__is_deleted=False), distinct=True),
    )
    if query:
        folder_q = Q()
        for variant in search_query_variants(query):
            folder_q |= Q(name__icontains=variant)
        folders = folders.filter(folder_q) if folder_q else folders.none()
    return folders.order_by("created_at", "pk") if sort == "oldest" else folders.order_by("-created_at", "-pk")


def gallery_photos_queryset(organ, folder_id, sort, query):
    qs = organ.photos.select_related("created_by", "created_department", "folder").filter(is_deleted=False).filter(Q(folder__isnull=True) | Q(folder__is_deleted=False))
    if folder_id:
        qs = qs.filter(folder_id=folder_id)
    else:
        qs = qs.filter(folder__isnull=True)
    if query:
        qs = qs.filter(photo_search_q(query))
    return qs.order_by("created_at", "pk") if sort == "oldest" else qs.order_by("-created_at", "-pk")


def photo_gallery_context(request, organ, user, folder_id_override=None):
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "newest")
    item_order = "photos" if request.GET.get("order") == "photos" else "folders"
    folder_id = str(folder_id_override) if folder_id_override is not None else request.GET.get("folder", "").strip()
    selected_folder = selected_photo_folder(organ, folder_id)

    folders = gallery_folders_queryset(organ, selected_folder, sort, query)
    photos_qs = gallery_photos_queryset(organ, folder_id, sort, query)

    paginator = Paginator(photos_qs, PHOTO_GALLERY_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    page_links = paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)

    folders_by_id = {folder.pk: folder for folder in organ.photo_folders.filter(is_deleted=False)}
    for photo in page.object_list:
        photo.folder_path = folder_path_from_map(photo.folder, folders_by_id) if photo.folder else []
    add_photo_asset_permissions(user, organ, folders, page.object_list)

    querystring = request.GET.copy()
    querystring.pop("page", None)
    folder_path_items = add_folder_content_counts(organ, folder_path(selected_folder))
    root_photo_count = organ.photos.filter(is_deleted=False, folder__isnull=True).count()
    root_folder_count = organ.photo_folders.filter(is_deleted=False, parent__isnull=True).count()
    total_photo_count = organ.photos.filter(is_deleted=False).filter(Q(folder__isnull=True) | Q(folder__is_deleted=False)).count()
    total_folder_count = len(folders_by_id)

    return {
        "organ": organ,
        "photos": page.object_list,
        "photo_page": page,
        "photo_page_links": page_links,
        "photo_querystring": querystring.urlencode(),
        "folders": folders,
        "photo_folder_count": len(folders),
        "photo_summary_count": page.paginator.count,
        "photo_summary_folder_count": len(folders),
        "photo_total_count": total_photo_count,
        "photo_total_folder_count": total_folder_count,
        "photo_root_count": root_photo_count,
        "photo_root_folder_count": root_folder_count,
        "selected_folder": selected_folder,
        "folder_path": folder_path_items,
        "photo_folder": folder_id,
        "can_write": can_write(user, organ),
        "can_upload_photos": can_upload_to_photo_folder(user, organ, selected_folder),
        "photo_query": query,
        "photo_sort": sort,
        "photo_item_order": item_order,
    }
