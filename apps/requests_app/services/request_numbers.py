from django.contrib.contenttypes.models import ContentType

from apps.requests_app.models import RequestNumberRegistry, normalize_request_number


REQUEST_NUMBER_DUPLICATE_MESSAGE = "Заявка с таким номером уже существует для выбранного территориального органа и отдела."


def request_content_type_for_model(model):
    return ContentType.objects.get_for_model(model, for_concrete_model=False)


def request_content_type_for_object(obj):
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def clean_request_number(request_number):
    return " ".join(str(request_number or "").split())


def request_number_conflict(organ, department, request_number, instance=None):
    normalized = normalize_request_number(request_number)
    if not normalized:
        return None
    qs = RequestNumberRegistry.objects.filter(
        territorial_organ=organ,
        department=department,
        normalized_request_number=normalized,
    )
    if instance and instance.pk:
        content_type = request_content_type_for_object(instance)
        qs = qs.exclude(content_type=content_type, object_id=instance.pk)
    return qs.select_related("territorial_organ", "content_type").first()


def validate_request_number(form, organ, table, instance=None):
    if "request_number" not in form.fields:
        return True
    cleaned_number = clean_request_number(form.cleaned_data.get("request_number"))
    if cleaned_number:
        form.cleaned_data["request_number"] = cleaned_number
    conflict = request_number_conflict(organ, table["department"], cleaned_number, instance)
    if conflict:
        form.add_error("request_number", REQUEST_NUMBER_DUPLICATE_MESSAGE)
        return False
    return True


def sync_request_number_registry(obj, department):
    if not hasattr(obj, "request_number"):
        return
    request_number = clean_request_number(getattr(obj, "request_number", ""))
    if not request_number:
        remove_request_number_registry(obj)
        return
    if getattr(obj, "request_number", None) != request_number:
        obj.request_number = request_number
        obj.save(update_fields=["request_number", "updated_at"])
    content_type = request_content_type_for_object(obj)
    RequestNumberRegistry.objects.update_or_create(
        content_type=content_type,
        object_id=obj.pk,
        defaults={
            "territorial_organ": obj.territorial_organ,
            "department": department,
            "request_number": request_number,
            "normalized_request_number": normalize_request_number(request_number),
        },
    )


def remove_request_number_registry(obj):
    if not obj or not getattr(obj, "pk", None):
        return
    content_type = request_content_type_for_object(obj)
    RequestNumberRegistry.objects.filter(content_type=content_type, object_id=obj.pk).delete()
