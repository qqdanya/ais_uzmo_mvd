from django.forms.models import model_to_dict
from pathlib import Path
from uuid import uuid4

from .middleware import get_current_request
from .models import AuditLog


def has_meaningful_changes(instance, old_values, new_values):
    """Return whether an update contains anything shown as an audit change."""
    if not isinstance(old_values, dict) or not isinstance(new_values, dict):
        return True

    # Import lazily because audit display constants build their model mapping
    # from the requests registry, which itself imports the request models.
    from .services.constants import MODEL_HIDDEN_FIELD_NAMES, SYSTEM_FIELD_NAMES

    model_name = instance.__class__.__name__ if instance is not None else ""
    hidden_fields = SYSTEM_FIELD_NAMES | MODEL_HIDDEN_FIELD_NAMES.get(model_name, set())
    keys = set(old_values) | set(new_values)
    return any(
        str(old_values.get(key)) != str(new_values.get(key))
        for key in keys - hidden_fields
    )


def client_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def serialize_instance(instance):
    data = model_to_dict(instance)
    return {key: str(value) for key, value in data.items()}


def object_message(action, instance):
    if instance is None:
        return ""
    if instance.__class__.__name__ == "TerritorialOrganPhoto":
        filename = Path(instance.image.name).name if getattr(instance, "image", None) else "фотография"
        return f"Фотография «{filename}»"
    if instance.__class__.__name__ == "TerritorialOrganPhotoFolder":
        folder_name = getattr(instance, "name", None) or str(instance)
        return f"Папка фотографий «{folder_name}»"
    if instance.__class__.__name__ == "TmcProduct":
        product_name = getattr(instance, "name", None) or str(instance)
        return f"Товар «{product_name}»"
    if instance.__class__.__name__ == "TmcRequestItem":
        item_name = getattr(instance, "name", None) or str(instance)
        return f"Позиция ТМЦ «{item_name}»"
    if instance.__class__.__name__ == "RequestStatusHistory":
        return "Изменение статуса заявки"
    return str(instance)


def write_audit(action, instance=None, user=None, old_values=None, new_values=None, request=None, event_type=""):
    values = new_values if isinstance(new_values, dict) else {}
    explicit_event = event_type or values.get("audit_event")
    if action == AuditLog.Action.UPDATE and not explicit_event and not has_meaningful_changes(instance, old_values, new_values):
        return None

    request = request or get_current_request()
    user = user or (request.user if request and request.user.is_authenticated else None)
    organ = getattr(instance, "territorial_organ", None) if instance is not None else None
    operation_id = ""
    if request is not None:
        operation_id = getattr(request, "_audit_operation_id", "")
        if not operation_id:
            operation_id = str(uuid4())
            request._audit_operation_id = operation_id
    AuditLog.objects.create(
        user=user,
        action=action,
        event_type=event_type,
        operation_id=operation_id,
        model_name=instance.__class__.__name__ if instance is not None else "",
        object_id=str(instance.pk) if instance is not None and instance.pk else "",
        object_repr=object_message(action, instance)[:255],
        old_values=old_values,
        new_values=new_values,
        territorial_organ=organ,
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
    )
