from dataclasses import dataclass
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit
from apps.directory.models import Department, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import RequestPhotoLink
from apps.requests_app.registry import TABLE_BY_KEY, get_table_or_404
from apps.requests_app.services.request_numbers import request_number_conflict, sync_request_number_registry

from .admin_common import DEPARTMENT_ICONS, field_value, request_number, request_title
from .admin_summary import available_organs_for_user


TRASH_PAGE_SIZE = 30
TRASH_SECTION_CHOICES = {"all", "requests", "photos", "folders"}


@dataclass(frozen=True)
class TrashActionResult:
    ok: bool
    message: str


def _deleted_folder_descendant_ids(folder):
    folder_ids = [folder.pk]
    pending = [folder.pk]
    while pending:
        child_ids = list(TerritorialOrganPhotoFolder.objects.filter(parent_id__in=pending).values_list("pk", flat=True))
        folder_ids.extend(child_ids)
        pending = child_ids
    return folder_ids


def _request_tables():
    seen = set()
    for table in TABLE_BY_KEY.values():
        key = table["key"]
        if key in seen:
            continue
        seen.add(key)
        yield table


def _request_model_has_field(model, field_name):
    return any(field.name == field_name for field in model._meta.fields)


def _department_names_by_slug(slugs):
    return dict(Department.objects.filter(is_active=True, slug__in=set(slugs)).values_list("slug", "name"))


def _request_deleted_rows(organs, query=""):
    rows = []
    query = (query or "").strip()
    tables = list(_request_tables())
    department_names = _department_names_by_slug(table["department"] for table in tables)
    for table in tables:
        model = table["model"]
        if not _request_model_has_field(model, "is_deleted"):
            continue
        qs = model.objects.select_related("territorial_organ", "updated_by", "created_by").filter(is_deleted=True, territorial_organ__in=organs)
        if query:
            filters = Q(territorial_organ__name__icontains=query) | Q(comment__icontains=query)
            if _request_model_has_field(model, "request_number"):
                filters |= Q(request_number__icontains=query)
            qs = qs.filter(filters)
        for obj in qs.order_by("-updated_at", "-pk")[:200]:
            rows.append(
                {
                    "kind": "request",
                    "table_key": table["key"],
                    "pk": obj.pk,
                    "title": request_title(table, obj),
                    "number": request_number(obj),
                    "organ": obj.territorial_organ,
                    "department": department_names.get(table["department"], table["department"]),
                    "department_slug": table["department"],
                    "department_icon": DEPARTMENT_ICONS.get(table["department"], "bi-folder2-open"),
                    "object": obj,
                    "updated_at": obj.updated_at,
                    "updated_by": obj.updated_by,
                    "restore_url": reverse("admin_trash_restore_request", kwargs={"table_key": table["key"], "pk": obj.pk}),
                    "detail_url": f'{reverse("admin_request_detail", kwargs={"table_key": table["key"], "pk": obj.pk})}?deleted=1',
                    "detail": field_value(obj, "comment") if hasattr(obj, "comment") else "",
                }
            )
    rows.sort(key=lambda item: (item["updated_at"] or datetime.min.replace(tzinfo=timezone.get_current_timezone()), item["pk"]), reverse=True)
    return rows


def _deleted_photos(organs, query=""):
    qs = (
        TerritorialOrganPhoto.objects.select_related("territorial_organ", "folder", "updated_by", "created_by")
        .filter(is_deleted=True, territorial_organ__in=organs)
        .annotate(link_count=Count("request_links", distinct=True))
    )
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(original_filename__icontains=query) | Q(description__icontains=query) | Q(territorial_organ__name__icontains=query) | Q(folder__name__icontains=query))
    return qs.order_by("-updated_at", "-pk")




def _folder_path(folder):
    if not folder:
        return ""
    names = []
    current = folder
    seen = set()
    while current and current.pk not in seen:
        seen.add(current.pk)
        name = (current.name or "").strip()
        if name and name.casefold() != "корень":
            names.append(name)
        current = current.parent
    return " / ".join(reversed(names))


def _attach_photo_folder_paths(photo_page):
    for photo in photo_page.object_list:
        photo.trash_folder_path = _folder_path(photo.folder)
    return photo_page

def _deleted_folders(organs, query=""):
    # Показываем в общем списке только те удалённые папки, которыми можно управлять
    # напрямую: корневые удалённые папки и папки, чей родитель активен/отсутствует.
    # Дочерние папки внутри уже удалённой ветки отображаются в мини-проводнике родителя.
    qs = (
        TerritorialOrganPhotoFolder.objects.select_related("territorial_organ", "parent", "updated_by", "created_by")
        .filter(is_deleted=True, territorial_organ__in=organs)
        .filter(Q(parent__isnull=True) | Q(parent__is_deleted=False))
        .annotate(photo_count=Count("photos", filter=Q(photos__is_deleted=True), distinct=True), child_count=Count("children", filter=Q(children__is_deleted=True), distinct=True))
    )
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(territorial_organ__name__icontains=query) | Q(parent__name__icontains=query))
    return qs.order_by("-updated_at", "-pk")


def _deleted_folder_ids_for_roots(root_ids):
    # Same breadth-first walk as _deleted_folder_descendant_ids, but for all
    # root folders on a trash page at once - one query per tree-depth level
    # for the whole page instead of one per folder.
    all_ids = set(root_ids)
    pending = list(root_ids)
    while pending:
        child_ids = list(TerritorialOrganPhotoFolder.objects.filter(parent_id__in=pending).values_list("pk", flat=True))
        new_ids = [child_id for child_id in child_ids if child_id not in all_ids]
        if not new_ids:
            break
        all_ids.update(new_ids)
        pending = new_ids
    return all_ids


def _attach_folder_tree_previews(folder_page, photos_per_folder=8):
    root_folders = list(folder_page.object_list)
    if not root_folders:
        return folder_page

    root_ids = {folder.pk for folder in root_folders}
    all_ids = _deleted_folder_ids_for_roots(root_ids)

    descendant_folders = (
        TerritorialOrganPhotoFolder.objects.select_related("parent")
        .filter(pk__in=all_ids)
        .only("id", "parent_id", "name", "territorial_organ_id")
        .order_by("name", "pk")
    )
    folder_by_id = {folder.pk: folder for folder in descendant_folders}
    for root in root_folders:
        folder_by_id[root.pk] = root

    children_by_parent = {}
    for folder in folder_by_id.values():
        if folder.pk in root_ids:
            continue
        children_by_parent.setdefault(folder.parent_id, []).append(folder)

    photos_by_folder = {folder_id: [] for folder_id in all_ids}
    photo_counts_by_folder = {folder_id: 0 for folder_id in all_ids}
    photos = (
        TerritorialOrganPhoto.objects.select_related("folder", "created_by", "updated_by")
        .filter(folder_id__in=all_ids, is_deleted=True)
        .order_by("folder__name", "-updated_at", "-pk")
    )
    for photo in photos:
        photo_counts_by_folder[photo.folder_id] = photo_counts_by_folder.get(photo.folder_id, 0) + 1
        bucket = photos_by_folder.setdefault(photo.folder_id, [])
        if len(bucket) < photos_per_folder:
            bucket.append(photo)

    def build_node(folder, depth=0):
        children = [build_node(child, depth + 1) for child in children_by_parent.get(folder.pk, [])]
        direct_photo_count = photo_counts_by_folder.get(folder.pk, 0)
        subtree_photo_count = direct_photo_count + sum(child["subtree_photo_count"] for child in children)
        subtree_folder_count = len(children) + sum(child["subtree_folder_count"] for child in children)
        return {
            "folder": folder,
            "depth": depth,
            "level": depth + 1,
            "children": children,
            "photos": photos_by_folder.get(folder.pk, []),
            "direct_photo_count": direct_photo_count,
            "direct_photos_truncated": direct_photo_count > len(photos_by_folder.get(folder.pk, [])),
            "subtree_photo_count": subtree_photo_count,
            "subtree_folder_count": subtree_folder_count,
        }

    for folder in root_folders:
        tree = build_node(folder_by_id.get(folder.pk, folder))
        folder.trash_tree_node = tree
        folder.trash_tree_folder_count = tree["subtree_folder_count"]
        folder.trash_tree_photo_count = tree["subtree_photo_count"]
    return folder_page

def _paginate(request, items, page_param):
    paginator = Paginator(items, TRASH_PAGE_SIZE)
    page = paginator.get_page(request.GET.get(page_param))
    return page, paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)


def _querystring_without(request, *names):
    query = request.GET.copy()
    for name in names:
        query.pop(name, None)
    return query.urlencode()


def build_trash_context(request):
    organs = list(available_organs_for_user(request.user))
    section = request.GET.get("section", "all")
    if section not in TRASH_SECTION_CHOICES:
        section = "all"
    query = request.GET.get("q", "").strip()

    request_rows = _request_deleted_rows(organs, query) if section in {"all", "requests"} else []
    photos = _deleted_photos(organs, query) if section in {"all", "photos"} else TerritorialOrganPhoto.objects.none()
    folders = _deleted_folders(organs, query) if section in {"all", "folders"} else TerritorialOrganPhotoFolder.objects.none()

    request_page, request_links = _paginate(request, request_rows, "requests_page")
    photo_page, photo_links = _paginate(request, photos, "photos_page")
    folder_page, folder_links = _paginate(request, folders, "folders_page")
    _attach_photo_folder_paths(photo_page)
    _attach_folder_tree_previews(folder_page)

    return {
        "active_tab": "trash",
        "section": section,
        "query": query,
        "is_leader": request.user.is_superuser,
        "request_page": request_page,
        "request_page_links": request_links,
        "photo_page": photo_page,
        "photo_page_links": photo_links,
        "folder_page": folder_page,
        "folder_page_links": folder_links,
        "request_querystring": _querystring_without(request, "requests_page"),
        "photo_querystring": _querystring_without(request, "photos_page"),
        "folder_querystring": _querystring_without(request, "folders_page"),
        "counts": {
            "requests": len(request_rows) if section in {"all", "requests"} else _request_deleted_count(organs),
            "photos": photos.count() if section in {"all", "photos"} else _deleted_photos(organs).count(),
            "folders": folders.count() if section in {"all", "folders"} else _deleted_folders(organs).count(),
        },
    }


def _request_deleted_count(organs):
    total = 0
    for table in _request_tables():
        model = table["model"]
        if _request_model_has_field(model, "is_deleted"):
            total += model.objects.filter(is_deleted=True, territorial_organ__in=organs).count()
    return total


def add_action_message(request, result):
    if result.ok:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)


def restore_request_record(request, table_key, pk):
    table = get_table_or_404(table_key)
    obj = get_object_or_404(table["model"], pk=pk, is_deleted=True)
    if obj.territorial_organ not in available_organs_for_user(request.user):
        raise PermissionDenied

    conflict = None
    if hasattr(obj, "request_number"):
        conflict = request_number_conflict(obj.territorial_organ, table["department"], getattr(obj, "request_number", ""), obj)
    if conflict:
        return TrashActionResult(False, "Нельзя восстановить запись: в этом органе и отделе уже есть активная заявка с таким номером.")

    old_values = serialize_instance(obj)
    with transaction.atomic():
        obj.is_deleted = False
        obj.updated_by = request.user
        obj.save(update_fields=["is_deleted", "updated_by", "updated_at"])
        sync_request_number_registry(obj, table["department"])
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values=old_values,
            new_values={"audit_event": "request_restored_from_trash", **serialize_instance(obj)},
            request=request,
        )
    return TrashActionResult(True, "Запись восстановлена и снова доступна в рабочей таблице.")


def restore_photo(request, pk):
    photo = get_object_or_404(TerritorialOrganPhoto.objects.select_related("folder", "territorial_organ"), pk=pk, is_deleted=True)
    if photo.territorial_organ not in available_organs_for_user(request.user):
        raise PermissionDenied
    if photo.folder_id and photo.folder.is_deleted:
        return TrashActionResult(False, "Нельзя восстановить фотографию: сначала восстановите папку, в которой она находится.")

    old_values = serialize_instance(photo)
    photo.is_deleted = False
    photo.updated_by = request.user
    photo.save(update_fields=["is_deleted", "updated_by", "updated_at"])
    write_audit(
        AuditLog.Action.UPDATE,
        photo,
        old_values=old_values,
        new_values={"audit_event": "photo_restored_from_trash", **serialize_instance(photo)},
        request=request,
    )
    return TrashActionResult(True, "Фотография восстановлена.")


def restore_folder_tree(request, pk):
    folder = get_object_or_404(TerritorialOrganPhotoFolder.objects.select_related("parent", "territorial_organ"), pk=pk, is_deleted=True)
    if folder.territorial_organ not in available_organs_for_user(request.user):
        raise PermissionDenied
    if folder.parent_id and folder.parent.is_deleted:
        return TrashActionResult(False, "Нельзя восстановить папку: сначала восстановите родительскую папку.")

    folder_ids = _deleted_folder_descendant_ids(folder)
    old_values = serialize_instance(folder)
    try:
        with transaction.atomic():
            now = timezone.now()
            TerritorialOrganPhotoFolder.objects.filter(pk__in=folder_ids).update(is_deleted=False, updated_by=request.user, updated_at=now)
            TerritorialOrganPhoto.objects.filter(territorial_organ=folder.territorial_organ, folder_id__in=folder_ids, is_deleted=True).update(is_deleted=False, updated_by=request.user, updated_at=now)
            folder.refresh_from_db()
            write_audit(
                AuditLog.Action.UPDATE,
                folder,
                old_values=old_values,
                new_values={"audit_event": "photo_folder_tree_restored_from_trash", "restored_folder_ids": folder_ids, **serialize_instance(folder)},
                request=request,
            )
    except IntegrityError:
        return TrashActionResult(False, "Нельзя восстановить папку: уже существует активная папка с таким же названием.")
    return TrashActionResult(True, "Папка, вложенные папки и фотографии восстановлены.")


def ensure_leader(user):
    if not user.is_superuser:
        raise PermissionDenied


def permanently_delete_photo(request, pk):
    ensure_leader(request.user)
    photo = get_object_or_404(TerritorialOrganPhoto.objects.select_related("territorial_organ", "folder"), pk=pk, is_deleted=True)
    if photo.territorial_organ not in available_organs_for_user(request.user):
        raise PermissionDenied

    old_values = serialize_instance(photo)
    file_name = photo.image.name if photo.image else ""
    original_filename = photo.original_filename
    link_count = RequestPhotoLink.objects.filter(photo=photo).count()
    with transaction.atomic():
        write_audit(
            AuditLog.Action.DELETE,
            photo,
            old_values=old_values,
            new_values={
                "audit_event": "photo_file_permanently_deleted",
                "file_name": file_name,
                "original_filename": original_filename,
                "file_size": photo.file_size,
                "request_photo_link_count": link_count,
            },
            request=request,
        )
        if photo.image:
            photo.image.delete(save=False)
        photo.delete()
    return TrashActionResult(True, "Фотография и файл на сервере безвозвратно удалены.")


def permanently_delete_folder_tree(request, pk):
    ensure_leader(request.user)
    folder = get_object_or_404(TerritorialOrganPhotoFolder.objects.select_related("territorial_organ", "parent"), pk=pk, is_deleted=True)
    if folder.territorial_organ not in available_organs_for_user(request.user):
        raise PermissionDenied

    folder_ids = _deleted_folder_descendant_ids(folder)
    active_folders = TerritorialOrganPhotoFolder.objects.filter(pk__in=folder_ids, is_deleted=False).count()
    photos_qs = TerritorialOrganPhoto.objects.filter(territorial_organ=folder.territorial_organ, folder_id__in=folder_ids)
    active_photos = photos_qs.filter(is_deleted=False).count()
    if active_folders or active_photos:
        return TrashActionResult(False, "Нельзя очистить папку: в дереве есть активные папки или фотографии.")

    photos = list(photos_qs.filter(is_deleted=True))
    old_values = serialize_instance(folder)
    file_names = [photo.image.name for photo in photos if photo.image]
    with transaction.atomic():
        write_audit(
            AuditLog.Action.DELETE,
            folder,
            old_values=old_values,
            new_values={
                "audit_event": "photo_folder_tree_permanently_deleted",
                "folder_ids": folder_ids,
                "photo_count": len(photos),
                "deleted_file_names": file_names[:30],
                "deleted_file_names_truncated": len(file_names) > 30,
            },
            request=request,
        )
        for photo in photos:
            if photo.image:
                photo.image.delete(save=False)
            photo.delete()
        TerritorialOrganPhotoFolder.objects.filter(pk__in=folder_ids).delete()
    return TrashActionResult(True, "Папка, вложенные папки и файлы фотографий безвозвратно удалены.")
