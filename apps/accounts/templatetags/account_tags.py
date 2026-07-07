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


@register.filter
def full_display_name(user):
    if not user:
        return "Система"
    profile = getattr(user, "profile", None)
    if profile:
        return profile.full_display_name
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()

# Shared admin select/dropdown helpers live in this existing tag library on purpose.
# Older deployments already load ``account_tags``; keeping the admin multiselect tag
# here avoids relying on discovery of a newly named template tag library.
from decimal import Decimal
from typing import Any


def _resolve_admin_select_attr(option: Any, attr: str | None) -> Any:
    if not attr:
        return None
    current = option
    for part in attr.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _admin_select_tuple_value(option: Any, index: int) -> Any:
    if isinstance(option, (list, tuple)) and len(option) > index:
        return option[index]
    return None


def _format_admin_select_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
    else:
        text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _admin_select_option_value(option: Any, value_attr: str | None) -> Any:
    if value_attr:
        value = _resolve_admin_select_attr(option, value_attr)
        if value is not None:
            return value
    tuple_value = _admin_select_tuple_value(option, 0)
    return option if tuple_value is None else tuple_value


def _admin_select_option_label(option: Any, label_attr: str | None, label_suffix: str | None) -> str:
    if label_attr == "organ_full_name":
        order_number = _format_admin_select_number(_resolve_admin_select_attr(option, "order_number"))
        name = _resolve_admin_select_attr(option, "name") or str(option)
        return f"{order_number}. {name}" if order_number else str(name)

    if label_attr == "user_display_name":
        text = display_name(option)
    elif label_attr:
        label = _resolve_admin_select_attr(option, label_attr)
        if label is not None:
            text = str(label)
        else:
            text = str(option)
    else:
        tuple_label = _admin_select_tuple_value(option, 1)
        text = str(tuple_label if tuple_label is not None else option)

    if label_suffix:
        return f"{text} {label_suffix}"
    return text


@register.inclusion_tag("partials/admin_multiselect.html")
def admin_multiselect(
    *,
    name: str,
    options: Any,
    selected_values: Any = None,
    current_label: str = "",
    empty_label: str = "Не выбрано",
    input_type: str = "checkbox",
    selected_value: Any = None,
    value_attr: str | None = None,
    label_attr: str | None = None,
    label_suffix: str | None = None,
    root_class: str = "",
    menu_class: str = "",
) -> dict[str, Any]:
    """Render a shared admin dropdown for checkbox/radio filters."""
    selected_as_strings = {str(value) for value in (selected_values or [])}
    selected_single = str(selected_value) if selected_value is not None else None
    normalized_options = []

    for option in options or []:
        value = _admin_select_option_value(option, value_attr)
        value_text = str(value)
        normalized_options.append(
            {
                "value": value_text,
                "label": _admin_select_option_label(option, label_attr, label_suffix),
                "checked": value_text == selected_single if input_type == "radio" else value_text in selected_as_strings,
            }
        )

    normalized_input_type = "radio" if input_type == "radio" else "checkbox"
    class_parts = ["dropdown", "admin-multiselect"]
    if normalized_input_type == "radio":
        class_parts.append("admin-multiselect-single")
    if root_class:
        class_parts.extend(str(root_class).split())

    menu_class_parts = ["dropdown-menu", "admin-multiselect-menu"]
    if menu_class:
        menu_class_parts.extend(str(menu_class).split())

    return {
        "name": name,
        "options": normalized_options,
        "current_label": current_label,
        "empty_label": empty_label,
        "input_type": normalized_input_type,
        "root_class": " ".join(class_parts),
        "menu_class": " ".join(menu_class_parts),
        "show_actions": normalized_input_type != "radio",
    }


def _parse_single_select_options(options: Any) -> list[dict[str, Any]]:
    if isinstance(options, str):
        parsed = []
        for raw_item in options.split("|"):
            item = raw_item.strip()
            if not item:
                continue
            if ":" in item:
                value, label = item.split(":", 1)
            else:
                value = label = item
            parsed.append((value.strip(), label.strip()))
        options = parsed

    normalized_options = []
    for option in options or []:
        value = _admin_select_option_value(option, None)
        label = _admin_select_option_label(option, None, None)
        disabled = False
        if isinstance(option, dict):
            value = option.get("value", value)
            label = option.get("label", label)
            disabled = bool(option.get("disabled"))
        normalized_options.append(
            {
                "value": str(value),
                "label": str(label),
                "disabled": disabled,
            }
        )
    return normalized_options


@register.inclusion_tag("partials/single_select.html")
def single_select(
    *,
    options: Any,
    selected_value: Any = "",
    name: str = "",
    id: str = "",
    aria_label: str = "",
    css_class: str = "form-select form-select-sm",
    data_admin_org_metric: bool = False,
    data_custom_select_skip: bool = False,
) -> dict[str, Any]:
    """Render a shared native single-select used by the custom select JS."""
    selected_text = str(selected_value if selected_value is not None else "")
    normalized_options = []
    for option in _parse_single_select_options(options):
        normalized_options.append(
            {
                **option,
                "selected": option["value"] == selected_text,
            }
        )
    return {
        "id": id,
        "name": name,
        "aria_label": aria_label,
        "css_class": css_class,
        "options": normalized_options,
        "data_admin_org_metric": data_admin_org_metric,
        "data_custom_select_skip": data_custom_select_skip,
    }

