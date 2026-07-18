from django.contrib.contenttypes.models import ContentType

from apps.audit.models import AuditLog
from apps.audit.utils import write_audit

from ..models import RequestStatusHistory


COMPLETED_DATE_FIELDS = {
    "citsizi-equipment": "due_date",
    "tmc-requests": "due_date",
}


def completed_date_field(table_key):
    return COMPLETED_DATE_FIELDS.get(table_key, "completed_at")


def status_history_content_type(obj):
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)


def status_history_queryset(obj):
    return RequestStatusHistory.objects.select_related("changed_by").filter(content_type=status_history_content_type(obj), object_id=obj.pk)


def attach_status_history_flags(objects, model):
    object_ids = [obj.pk for obj in objects]
    if not object_ids:
        return
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    history_ids = set(
        RequestStatusHistory.objects.filter(content_type=content_type, object_id__in=object_ids).values_list("object_id", flat=True)
    )
    for obj in objects:
        obj.has_status_history_entries = obj.pk in history_ids


def create_status_history(obj, old_status, new_status, completed_at, changed_by, note):
    return RequestStatusHistory.objects.create(
        content_type=status_history_content_type(obj),
        object_id=obj.pk,
        old_status=old_status,
        new_status=new_status,
        completed_at=completed_at,
        changed_by=changed_by,
        note=note,
    )


def write_status_change_audit_event(obj, old_values, new_values, request):
    event_values = dict(new_values or {})
    event_values["audit_event"] = "request_status_changed"
    write_audit(
        AuditLog.Action.UPDATE,
        obj,
        old_values=old_values,
        new_values=event_values,
        request=request,
    )
