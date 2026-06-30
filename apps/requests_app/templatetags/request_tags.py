from django import template
from django import forms
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


@register.simple_tag
def expiry_date_cell(obj):
    expiry_date = getattr(obj, "expiry_date", None)
    if not expiry_date:
        return "-"
    date_text = expiry_date.strftime("%d.%m.%Y")
    days_left = (expiry_date - timezone.localdate()).days
    if days_left < 0:
        return format_html(
            '<span class="expiry-cell"><span>{}</span><span class="status-badge status-rejected" data-bs-toggle="tooltip" data-bs-title="Срок эксплуатации истек"><i class="bi bi-exclamation-triangle"></i> Истек</span></span>',
            date_text,
        )
    if days_left <= 30:
        return format_html(
            '<span class="expiry-cell"><span>{}</span><span class="status-badge status-in_work" data-bs-toggle="tooltip" data-bs-title="Срок эксплуатации истекает через {} дн."><i class="bi bi-exclamation-triangle"></i> Скоро истекает</span></span>',
            date_text,
            days_left,
        )
    return date_text


@register.filter
def model_fields(model):
    return [field for field in model._meta.fields if field.name not in {"id", "is_deleted"}]


@register.simple_tag
def row_class(table_key, obj):
    return ""


@register.filter
def is_select_field(bound_field):
    return isinstance(bound_field.field.widget, forms.Select)


@register.filter
def option_selected(bound_field, value):
    selected = bound_field.value()
    if selected is None:
        selected = ""
    return str(selected) == str(value)


@register.filter
def in_list(value, values):
    return value in values


@register.simple_tag
def selected_choice_label(bound_field):
    selected = bound_field.value()
    if selected is None:
        selected = ""
    selected = str(selected)
    for value, label in bound_field.field.choices:
        if str(value) == selected:
            return label
    return ""
