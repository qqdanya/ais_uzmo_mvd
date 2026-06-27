from django import template
from django.utils.html import format_html
from django.utils import timezone

register = template.Library()


@register.filter
def get_attr(obj, name):
    display = getattr(obj, f"get_{name}_display", None)
    value = display() if callable(display) else getattr(obj, name)
    if hasattr(value, "all"):
        return ", ".join(str(item) for item in value.all())
    return value


@register.simple_tag
def status_badge(obj):
    status = getattr(obj, "status", "")
    label = getattr(obj, "get_status_display", lambda: status)()
    return format_html('<span class="status-badge status-{}">{}</span>', status, label)


@register.filter
def model_fields(model):
    return [field for field in model._meta.fields if field.name not in {"id", "is_deleted"}]


@register.simple_tag
def row_class(table_key, obj):
    if table_key != "fire-extinguishers":
        return ""
    expiry_date = getattr(obj, "expiry_date", None)
    if not expiry_date:
        return ""
    today = timezone.localdate()
    days_left = (expiry_date - today).days
    if days_left < 0:
        return "row-expired"
    if days_left <= 30:
        return "row-expiring"
    return ""
