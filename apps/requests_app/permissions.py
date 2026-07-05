from apps.accounts.models import UserProfile


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
        departments = profile.allowed_departments.all()
        # Empty department list means no department restriction.
        # If departments are explicitly assigned, operator can write only within them.
        if departments.exists() and not departments.filter(slug=department_slug).exists():
            return False
    if organ is None:
        return True
    allowed = profile.allowed_organs.all()
    return not allowed.exists() or allowed.filter(pk=organ.pk).exists()


def writable_department_ids(user):
    if role_for(user) == UserProfile.Role.ADMIN:
        return None
    profile = getattr(user, "profile", None)
    if not profile:
        return set()
    return set(profile.allowed_departments.values_list("pk", flat=True))


def user_primary_department(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return None
    return profile.allowed_departments.order_by("order_number", "name").first()


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
    if not profile or profile.role == UserProfile.Role.OBSERVER:
        return True
    allowed = profile.allowed_organs.all()
    return not allowed.exists() or allowed.filter(pk=organ.pk).exists()
