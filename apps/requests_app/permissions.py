from apps.accounts.models import UserProfile


def role_for(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return UserProfile.Role.ADMIN
    profile = getattr(user, "profile", None)
    return getattr(profile, "role", UserProfile.Role.OBSERVER)


def can_write(user, organ=None):
    role = role_for(user)
    if role == UserProfile.Role.ADMIN:
        return True
    if role != UserProfile.Role.OPERATOR:
        return False
    if organ is None:
        return True
    profile = getattr(user, "profile", None)
    allowed = profile.allowed_organs.all()
    return not allowed.exists() or allowed.filter(pk=organ.pk).exists()


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
