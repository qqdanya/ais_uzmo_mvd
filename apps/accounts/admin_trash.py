from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit
from apps.directory.models import Department, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import RequestPhotoLink, RequestResponse
from apps.requests_app.permissions import can_manage_photo_asset, can_write, cached_allowed_department_ids, cached_allowed_organ_ids
from apps.requests_app.registry import TABLE_BY_KEY, get_table_or_404
from apps.requests_app.services.request_photos import photo_snapshot_for_audit
from apps.requests_app.services.request_numbers import request_number_conflict, sync_request_number_registry
from apps.requests_app.services.request_responses import (
    attach_request_response_summaries,
    request_response_row_data,
)

from .admin_common import DEPARTMENT_ICONS, field_value, request_number, request_title
from .admin_summary import available_organs_for_user
from .models import TrashDismissal, UserProfile


TRASH_PAGE_SIZE = 30
TRASH_SECTION_CHOICES = {"all", "requests", "photos", "folders"}
PERSONAL_TRASH_RETENTION_DAYS = 90


def _is_admin_user(user):
    return user.is_superuser or getattr(getattr(user, "profile", None), "role", "") == UserProfile.Role.ADMIN


def _dismissed_ids(user, kind, table_key="", personal=False):
    if _is_admin_user(user) and not personal:
        return set()
    return set(TrashDismissal.objects.filter(user=user, kind=kind, table_key=table_key).values_list("object_id", flat=True))


def _personal_trash_cutoff():
    return timezone.now() - timedelta(days=PERSONAL_TRASH_RETENTION_DAYS)


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


def _request_deleted_rows(organs, query="", user=None, personal=False):
    rows = []
    query = (query or "").strip()
    tables = list(_request_tables())
    department_names = _department_names_by_slug(table["department"] for table in tables)
    for table in tables:
        if user is not None and not can_write(user, department_slug=table["department"]):
            continue
        model = table["model"]
        if not _request_model_has_field(model, "is_deleted"):
            continue
        has_request_reference = _request_model_has_field(model, "request_number")
        qs = model.objects.select_related("territorial_organ", "updated_by", "created_by").filter(is_deleted=True, territorial_organ__in=organs)
        if user is not None and (personal or not _is_admin_user(user)):
            qs = qs.filter(updated_by=user, updated_at__gte=_personal_trash_cutoff()).exclude(pk__in=_dismissed_ids(user, "request", table["key"], personal=True))
        if query:
            filters = Q(territorial_organ__name__icontains=query) | Q(comment__icontains=query)
            if has_request_reference:
                filters |= Q(request_number__icontains=query)
                matching_responses = RequestResponse.objects.filter(
                    content_type=ContentType.objects.get_for_model(model, for_concrete_model=False),
                    object_id=OuterRef("pk"),
                    response_number__icontains=query,
                )
                qs = qs.annotate(response_search_match=Exists(matching_responses))
                filters |= Q(response_search_match=True)
            qs = qs.filter(filters)
        objects = list(qs.order_by("-updated_at", "-pk")[:200])
        if has_request_reference:
            attach_request_response_summaries(objects, model)
        for obj in objects:
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
                    "has_request_reference": has_request_reference,
                    **request_response_row_data(obj),
                }
            )
    rows.sort(key=lambda item: (item["updated_at"] or datetime.min.replace(tzinfo=timezone.get_current_timezone()), item["pk"]), reverse=True)
    return rows


def _deleted_photos(organs, query="", user=None, personal=False):
    qs = (
        TerritorialOrganPhoto.objects.select_related("territorial_organ", "folder", "updated_by", "created_by")
        .filter(is_deleted=True, territorial_organ__in=organs)
        .annotate(link_count=Count("request_links", distinct=True))
    )
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(original_filename__icontains=query) | Q(description__icontains=query) | Q(territorial_organ__name__icontains=query) | Q(folder__name__icontains=query))
    photos = qs.order_by("-updated_at", "-pk")
    if user is None or (_is_admin_user(user) and not personal):
        return photos
    dismissed = _dismissed_ids(user, "photo", personal=True)
    cutoff = _personal_trash_cutoff()
    return [photo for photo in photos if photo.updated_by_id == user.pk and photo.updated_at >= cutoff and photo.pk not in dismissed and can_manage_photo_asset(user, photo.territorial_organ, photo)]




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

def _deleted_folders(organs, query="", user=None, personal=False):
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
    folders = qs.order_by("-updated_at", "-pk")
    if user is None or (_is_admin_user(user) and not personal):
        return folders
    dismissed = _dismissed_ids(user, "folder", personal=True)
    cutoff = _personal_trash_cutoff()
    return [folder for folder in folders if folder.updated_by_id == user.pk and folder.updated_at >= cutoff and folder.pk not in dismissed and can_manage_photo_asset(user, folder.territorial_organ, folder)]


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


def build_trash_context(request, *, personal=False):
    organs = list(available_organs_for_user(request.user))
    section = request.GET.get("section", "all")
    if section not in TRASH_SECTION_CHOICES:
        section = "all"
    query = request.GET.get("q", "").strip()

    request_rows = _request_deleted_rows(organs, query, request.user, personal) if section in {"all", "requests"} else []
    photos = _deleted_photos(organs, query, request.user, personal) if section in {"all", "photos"} else []
    folders = _deleted_folders(organs, query, request.user, personal) if section in {"all", "folders"} else []

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
        "is_personal_trash": personal,
        "show_admin_navigation": not personal,
        "trash_panel_url_name": "trash_panel" if personal else "admin_trash_panel",
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
            "requests": len(request_rows) if section in {"all", "requests"} else _request_deleted_count(organs, request.user, personal),
            "photos": len(photos) if section in {"all", "photos"} else _deleted_photos_count(organs, user=request.user, personal=personal),
            "folders": len(folders) if section in {"all", "folders"} else _deleted_folders_count(organs, user=request.user, personal=personal),
        },
    }


def _request_deleted_count(organs, user=None, personal=False):
    total = 0
    for table in _request_tables():
        if user is not None and not can_write(user, department_slug=table["department"]):
            continue
        model = table["model"]
        if _request_model_has_field(model, "is_deleted"):
            qs = model.objects.filter(is_deleted=True, territorial_organ__in=organs)
            if user is not None and (personal or not _is_admin_user(user)):
                qs = qs.filter(updated_by=user, updated_at__gte=_personal_trash_cutoff()).exclude(pk__in=_dismissed_ids(user, "request", table["key"], personal=True))
            total += qs.count()
    return total


def _personal_asset_count_qs(qs, user, kind):
    """SQL equivalent of the python filter chain in _deleted_photos/_deleted_folders
    (updated_by / retention cutoff / dismissals / can_manage_photo_asset), so the
    menu badge can COUNT instead of loading every deleted object with its
    annotations and running a per-object permission check.
    """
    qs = qs.filter(updated_by=user, updated_at__gte=_personal_trash_cutoff()).exclude(pk__in=_dismissed_ids(user, kind, personal=True))
    if _is_admin_user(user):
        return qs
    # can_manage_photo_asset for an operator: can_write(user, organ) - which
    # requires a non-empty allowed-departments set and the asset's organ to be
    # allowed - plus either the asset's created_department is writable, or it
    # has no created_department and was created by this user (or nobody).
    department_ids = cached_allowed_department_ids(user)
    if not department_ids:
        return qs.none()
    return qs.filter(territorial_organ_id__in=cached_allowed_organ_ids(user)).filter(
        Q(created_department_id__in=department_ids)
        | (Q(created_department__isnull=True) & (Q(created_by__isnull=True) | Q(created_by=user)))
    )


def _deleted_photos_count(organs, user=None, personal=False):
    qs = TerritorialOrganPhoto.objects.filter(is_deleted=True, territorial_organ__in=organs)
    if user is None or (_is_admin_user(user) and not personal):
        return qs.count()
    return _personal_asset_count_qs(qs, user, "photo").count()


def _deleted_folders_count(organs, user=None, personal=False):
    qs = TerritorialOrganPhotoFolder.objects.filter(is_deleted=True, territorial_organ__in=organs).filter(
        Q(parent__isnull=True) | Q(parent__is_deleted=False)
    )
    if user is None or (_is_admin_user(user) and not personal):
        return qs.count()
    return _personal_asset_count_qs(qs, user, "folder").count()


PERSONAL_TRASH_COUNT_CACHE_TTL = 60


def _personal_trash_count_cache_key(user):
    return f"personal-trash-count:{user.pk}"


def _compute_personal_trash_count(user):
    if not getattr(user, "is_authenticated", False):
        return 0
    profile = getattr(user, "profile", None)
    if not user.is_superuser and getattr(profile, "role", "") not in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR}:
        return 0
    organs = list(available_organs_for_user(user))
    return (
        _request_deleted_count(organs, user, personal=True)
        + _deleted_photos_count(organs, user=user, personal=True)
        + _deleted_folders_count(organs, user=user, personal=True)
    )


def personal_trash_count(user):
    """Cached: this runs on every page render (the user-menu badge), so it
    must not cost a dozen COUNTs per request. Staleness is bounded by the
    TTL, and refresh_personal_trash_count() writes through after any action
    that changes this user's own trash (the badge JS also refetches the
    fresh endpoint after every mutating htmx request).
    """
    if not getattr(user, "is_authenticated", False):
        return 0
    key = _personal_trash_count_cache_key(user)
    count = cache.get(key)
    if count is None:
        count = _compute_personal_trash_count(user)
        cache.set(key, count, PERSONAL_TRASH_COUNT_CACHE_TTL)
    return count


def refresh_personal_trash_count(user):
    count = _compute_personal_trash_count(user)
    if getattr(user, "is_authenticated", False):
        cache.set(_personal_trash_count_cache_key(user), count, PERSONAL_TRASH_COUNT_CACHE_TTL)
    return count


def dismiss_trash_item(request, kind, pk, table_key=""):
    if kind == "request":
        table = get_table_or_404(table_key)
        obj = get_object_or_404(table["model"], pk=pk, is_deleted=True, updated_by=request.user)
        if not can_write(request.user, obj.territorial_organ, table["department"]):
            raise PermissionDenied
    elif kind == "photo":
        obj = get_object_or_404(TerritorialOrganPhoto.objects.select_related("territorial_organ"), pk=pk, is_deleted=True, updated_by=request.user)
        if not can_manage_photo_asset(request.user, obj.territorial_organ, obj):
            raise PermissionDenied
    elif kind == "folder":
        obj = get_object_or_404(TerritorialOrganPhotoFolder.objects.select_related("territorial_organ"), pk=pk, is_deleted=True, updated_by=request.user)
        if not can_manage_photo_asset(request.user, obj.territorial_organ, obj):
            raise PermissionDenied
    else:
        raise PermissionDenied
    TrashDismissal.objects.get_or_create(user=request.user, kind=kind, table_key=table_key, object_id=pk)
    write_audit(
        AuditLog.Action.UPDATE,
        obj,
        new_values={"audit_event": AuditLog.EventType.PERSONAL_TRASH_ITEM_REMOVED, "kind": kind},
        request=request,
    )
    refresh_personal_trash_count(request.user)
    return TrashActionResult(True, "Объект убран из вашей корзины.")


def clear_personal_trash(request):
    organs = list(available_organs_for_user(request.user))
    dismissals = []
    cutoff = _personal_trash_cutoff()
    for table in _request_tables():
        if not can_write(request.user, department_slug=table["department"]):
            continue
        model = table["model"]
        if not _request_model_has_field(model, "is_deleted"):
            continue
        ids = model.objects.filter(is_deleted=True, territorial_organ__in=organs, updated_by=request.user, updated_at__gte=cutoff).values_list("pk", flat=True)
        dismissals.extend(TrashDismissal(user=request.user, kind="request", table_key=table["key"], object_id=pk) for pk in ids)
    dismissals.extend(TrashDismissal(user=request.user, kind="photo", object_id=photo.pk) for photo in _deleted_photos(organs, user=request.user, personal=True))
    dismissals.extend(TrashDismissal(user=request.user, kind="folder", object_id=folder.pk) for folder in _deleted_folders(organs, user=request.user, personal=True))
    TrashDismissal.objects.bulk_create(dismissals, ignore_conflicts=True)
    write_audit(
        AuditLog.Action.UPDATE,
        user=request.user,
        new_values={"audit_event": AuditLog.EventType.PERSONAL_TRASH_CLEARED, "object_count": len(dismissals)},
        request=request,
    )
    refresh_personal_trash_count(request.user)
    return TrashActionResult(True, "Корзина очищена.")


def add_action_message(request, result):
    if result.ok:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)


def restore_request_record(request, table_key, pk):
    table = get_table_or_404(table_key)
    obj = get_object_or_404(table["model"], pk=pk, is_deleted=True)
    if obj.territorial_organ not in available_organs_for_user(request.user) or not can_write(request.user, obj.territorial_organ, table["department"]):
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
        TrashDismissal.objects.filter(kind="request", table_key=table_key, object_id=obj.pk).delete()
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
    if photo.territorial_organ not in available_organs_for_user(request.user) or not can_manage_photo_asset(request.user, photo.territorial_organ, photo):
        raise PermissionDenied
    if photo.folder_id and photo.folder.is_deleted:
        return TrashActionResult(False, "Нельзя восстановить фотографию: сначала восстановите папку, в которой она находится.")

    old_values = serialize_instance(photo)
    photo.is_deleted = False
    photo.updated_by = request.user
    photo.save(update_fields=["is_deleted", "updated_by", "updated_at"])
    TrashDismissal.objects.filter(kind="photo", object_id=photo.pk).delete()
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
    if folder.territorial_organ not in available_organs_for_user(request.user) or not can_manage_photo_asset(request.user, folder.territorial_organ, folder):
        raise PermissionDenied
    if folder.parent_id and folder.parent.is_deleted:
        return TrashActionResult(False, "Нельзя восстановить папку: сначала восстановите родительскую папку.")

    folder_ids = _deleted_folder_descendant_ids(folder)
    old_values = serialize_instance(folder)
    restored_photos = TerritorialOrganPhoto.objects.filter(
        territorial_organ=folder.territorial_organ,
        folder_id__in=folder_ids,
        is_deleted=True,
    )
    photo_snapshot = photo_snapshot_for_audit(photos=restored_photos)
    try:
        with transaction.atomic():
            now = timezone.now()
            TerritorialOrganPhotoFolder.objects.filter(pk__in=folder_ids).update(is_deleted=False, updated_by=request.user, updated_at=now)
            TerritorialOrganPhoto.objects.filter(territorial_organ=folder.territorial_organ, folder_id__in=folder_ids, is_deleted=True).update(is_deleted=False, updated_by=request.user, updated_at=now)
            TrashDismissal.objects.filter(Q(kind="folder", object_id__in=folder_ids) | Q(kind="photo", object_id__in=TerritorialOrganPhoto.objects.filter(folder_id__in=folder_ids).values("pk"))).delete()
            folder.refresh_from_db()
            write_audit(
                AuditLog.Action.UPDATE,
                folder,
                old_values=old_values,
                new_values={
                    "audit_event": "photo_folder_tree_restored_from_trash",
                    "restored_folder_ids": folder_ids,
                    **photo_snapshot,
                    **serialize_instance(folder),
                },
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
    return TrashActionResult(True, "Фотография удалена без возможности восстановления.")


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
    photo_snapshot = photo_snapshot_for_audit(photos=photos_qs.filter(is_deleted=True))
    file_names = [photo.image.name for photo in photos if photo.image]
    with transaction.atomic():
        write_audit(
            AuditLog.Action.DELETE,
            folder,
            old_values=old_values,
            new_values={
                "audit_event": "photo_folder_tree_permanently_deleted",
                "folder_ids": folder_ids,
                **photo_snapshot,
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
    return TrashActionResult(True, "Папка и всё её содержимое удалены без возможности восстановления.")
