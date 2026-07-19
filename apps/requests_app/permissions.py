from apps.accounts.models import UserProfile
from apps.directory.models import Department


def permission_cache(user):
    cache = getattr(user, "_request_permission_cache", None)
    if cache is None:
        cache = {}
        setattr(user, "_request_permission_cache", cache)
    return cache


def cached_allowed_departments(user):
    cache = permission_cache(user)
    if "allowed_departments" not in cache:
        profile = getattr(user, "profile", None)
        cache["allowed_departments"] = list(profile.allowed_departments.all()) if profile else []
    return cache["allowed_departments"]


def cached_allowed_department_ids(user):
    cache = permission_cache(user)
    if "allowed_department_ids" not in cache:
        cache["allowed_department_ids"] = {department.pk for department in cached_allowed_departments(user)}
    return cache["allowed_department_ids"]


def cached_allowed_department_slugs(user):
    cache = permission_cache(user)
    if "allowed_department_slugs" not in cache:
        cache["allowed_department_slugs"] = {department.slug for department in cached_allowed_departments(user)}
    return cache["allowed_department_slugs"]


def cached_allowed_organ_ids(user):
    cache = permission_cache(user)
    if "allowed_organ_ids" not in cache:
        profile = getattr(user, "profile", None)
        cache["allowed_organ_ids"] = {organ.pk for organ in profile.allowed_organs.all()} if profile else set()
    return cache["allowed_organ_ids"]


def cached_writable_departments(user):
    cache = permission_cache(user)
    if "writable_departments" not in cache:
        profile = getattr(user, "profile", None)
        cache["writable_departments"] = list(profile.writable_departments.all()) if profile else []
    return cache["writable_departments"]


def cached_writable_department_ids(user):
    cache = permission_cache(user)
    if "writable_department_ids" not in cache:
        cache["writable_department_ids"] = {department.pk for department in cached_writable_departments(user)}
    return cache["writable_department_ids"]


def cached_writable_department_slugs(user):
    cache = permission_cache(user)
    if "writable_department_slugs" not in cache:
        cache["writable_department_slugs"] = {department.slug for department in cached_writable_departments(user)}
    return cache["writable_department_slugs"]


def cached_writable_organ_ids(user):
    cache = permission_cache(user)
    if "writable_organ_ids" not in cache:
        profile = getattr(user, "profile", None)
        cache["writable_organ_ids"] = {organ.pk for organ in profile.writable_organs.all()} if profile else set()
    return cache["writable_organ_ids"]


def cached_active_department_slugs(user):
    cache = permission_cache(user)
    if "active_department_slugs" not in cache:
        cache["active_department_slugs"] = set(Department.objects.filter(is_active=True).values_list("slug", flat=True))
    return cache["active_department_slugs"]


def role_for(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return UserProfile.Role.ADMIN
    profile = getattr(user, "profile", None)
    return getattr(profile, "role", UserProfile.Role.OBSERVER)


def can_write(user, organ=None, department_slug=None):
    role = role_for(user)
    if role == UserProfile.Role.ADMIN:
        return True
    if role != UserProfile.Role.OPERATOR:
        return False
    profile = getattr(user, "profile", None)
    if not profile:
        return False
    if department_slug:
        department_exists = department_slug in cached_active_department_slugs(user)
        if department_exists and department_slug not in cached_writable_department_slugs(user):
            return False
    if organ is not None and organ.pk not in cached_writable_organ_ids(user):
        return False
    if department_slug or organ is not None:
        return True
    return bool(cached_writable_department_ids(user) or cached_writable_organ_ids(user))


def writable_department_ids(user):
    if role_for(user) == UserProfile.Role.ADMIN:
        return None
    profile = getattr(user, "profile", None)
    if not profile:
        return set()
    return cached_writable_department_ids(user)


def user_primary_department(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return None
    return profile.writable_departments.order_by("order_number", "name").first()


def can_manage_photo_asset(user, organ, asset):
    if not can_write(user, organ):
        return False
    if role_for(user) == UserProfile.Role.ADMIN:
        return True
    department_id = getattr(asset, "created_department_id", None)
    if department_id:
        return department_id in writable_department_ids(user)
    created_by_id = getattr(asset, "created_by_id", None)
    return created_by_id in (None, user.pk)


def can_view(user, organ=None):
    if role_for(user) == UserProfile.Role.ADMIN:
        return True
    if organ is None:
        return user.is_authenticated
    profile = getattr(user, "profile", None)
    if not profile:
        return False
    return organ.pk in cached_allowed_organ_ids(user)


def can_preview_photo_asset(user, organ, photo):
    if photo.territorial_organ_id != organ.pk:
        return False
    if photo.is_deleted:
        return role_for(user) == UserProfile.Role.ADMIN or can_manage_photo_asset(user, organ, photo)
    if not can_view(user, organ):
        return False
    return not photo.folder_id or not photo.folder.is_deleted
