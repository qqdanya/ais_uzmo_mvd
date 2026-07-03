from django.forms.models import model_to_dict
from pathlib import Path

from .middleware import get_current_request
from .models import AuditLog


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
    feminine_action_words = {
        AuditLog.Action.CREATE: "Создана",
        AuditLog.Action.UPDATE: "Изменена",
        AuditLog.Action.DELETE: "Удалена",
    }
    masculine_action_words = {
        AuditLog.Action.CREATE: "Создан",
        AuditLog.Action.UPDATE: "Изменен",
        AuditLog.Action.DELETE: "Удален",
    }
    neuter_action_words = {
        AuditLog.Action.CREATE: "Создано",
        AuditLog.Action.UPDATE: "Изменено",
        AuditLog.Action.DELETE: "Удалено",
    }
    action_word = feminine_action_words.get(action, "Изменена")
    if instance.__class__.__name__ == "TerritorialOrganPhoto":
        filename = Path(instance.image.name).name if getattr(instance, "image", None) else "фотография"
        return f"{action_word} фотография «{filename}»"
    if instance.__class__.__name__ == "TerritorialOrganPhotoFolder":
        folder_name = getattr(instance, "name", None) or str(instance)
        return f"{action_word} папка фотографий «{folder_name}»"
    if instance.__class__.__name__ == "TmcProduct":
        product_name = getattr(instance, "name", None) or str(instance)
        return f"{masculine_action_words.get(action, 'Изменен')} товар «{product_name}»"
    if instance.__class__.__name__ == "TmcRequestItem":
        item_name = getattr(instance, "name", None) or str(instance)
        return f"{feminine_action_words.get(action, 'Изменена')} позиция ТМЦ «{item_name}»"
    if instance.__class__.__name__ == "RequestStatusHistory":
        return f"{neuter_action_words.get(action, 'Изменено')} изменение статуса заявки"
    return f"{action_word} запись «{str(instance)}»"


def write_audit(action, instance=None, user=None, old_values=None, new_values=None, request=None):
    request = request or get_current_request()
    user = user or (request.user if request and request.user.is_authenticated else None)
    organ = getattr(instance, "territorial_organ", None) if instance is not None else None
    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=instance.__class__.__name__ if instance is not None else "",
        object_id=str(instance.pk) if instance is not None and instance.pk else "",
        object_repr=object_message(action, instance)[:255],
        old_values=old_values,
        new_values=new_values,
        territorial_organ=organ,
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
    )
