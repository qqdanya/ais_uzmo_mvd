from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F, Prefetch, Window
from django.db.models.functions import RowNumber

from ..models import RequestResponse


RESPONSE_ORDERING = ("-response_date", "-created_at", "-pk")


def request_response_content_type(request_object_or_model):
    return ContentType.objects.get_for_model(request_object_or_model, for_concrete_model=False)


def request_response_queryset(request_object):
    return (
        RequestResponse.objects.select_related("created_by", "updated_by")
        .filter(
            content_type=request_response_content_type(request_object),
            object_id=request_object.pk,
        )
        .order_by(*RESPONSE_ORDERING)
    )


def attach_request_response_summaries(objects, model):
    """Attach one latest-response preview and a count without per-row queries."""
    objects = list(objects)
    for obj in objects:
        obj.response_count = 0
        obj.response_extra_count = 0
        obj.latest_response = None

    object_ids = [obj.pk for obj in objects if obj.pk]
    if not object_ids:
        return objects

    rows = (
        RequestResponse.objects.filter(
            content_type=request_response_content_type(model),
            object_id__in=object_ids,
        )
        .annotate(
            response_total=Window(
                expression=Count("pk"),
                partition_by=[F("object_id")],
            ),
            response_rank=Window(
                expression=RowNumber(),
                partition_by=[F("object_id")],
                order_by=[
                    F("response_date").desc(),
                    F("created_at").desc(),
                    F("pk").desc(),
                ],
            ),
        )
        .filter(response_rank=1)
        .order_by("object_id")
        .only(
            "id",
            "object_id",
            "response_number",
            "response_date",
            "created_at",
        )
    )
    objects_by_id = {obj.pk: obj for obj in objects}
    for response in rows:
        obj = objects_by_id.get(response.object_id)
        if obj is None:
            continue
        obj.response_count = response.response_total
        obj.latest_response = response

    for obj in objects:
        obj.response_extra_count = max(obj.response_count - 1, 0)
    return objects


def request_response_row_data(obj):
    latest = getattr(obj, "latest_response", None)
    return {
        "response_count": getattr(obj, "response_count", 0),
        "response_extra_count": getattr(obj, "response_extra_count", 0),
        "latest_response_number": latest.response_number if latest else "",
        "latest_response_date": latest.response_date if latest else None,
        "latest_response_date_display": latest.response_date.strftime("%d.%m.%Y") if latest else "",
    }


def prefetch_request_responses_for_export(queryset):
    if not hasattr(queryset, "prefetch_related"):
        return queryset
    response_queryset = RequestResponse.objects.order_by(*RESPONSE_ORDERING).only(
        "id",
        "content_type_id",
        "object_id",
        "response_number",
        "response_date",
        "created_at",
    )
    return queryset.prefetch_related(
        Prefetch("responses", queryset=response_queryset, to_attr="export_responses")
    )


def response_document_label(response):
    return f"{response.response_number} от {response.response_date:%d.%m.%Y}"


def request_response_export_value(obj, *, multiline=True):
    request_number = str(getattr(obj, "request_number", "") or "")
    responses = list(getattr(obj, "export_responses", ()) or ())
    if not responses:
        return request_number
    response_labels = [response_document_label(response) for response in responses]
    if multiline:
        return "\n".join([request_number, *response_labels])
    return f"{request_number} / {'; '.join(response_labels)}"


def request_response_audit_snapshot(response):
    return {
        "response_id": str(response.pk or ""),
        "response_number": response.response_number,
        "response_date": response.response_date.isoformat() if response.response_date else "",
        "note": response.note,
    }
