from django import template


register = template.Library()


@register.filter
def display_name(user):
    if not user:
        return "Система"
    profile = getattr(user, "profile", None)
    if profile:
        return profile.display_name
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()
