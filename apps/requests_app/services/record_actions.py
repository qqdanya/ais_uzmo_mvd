from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit

from ..models import NeedStatus
from .request_numbers import sync_request_number_registry, remove_request_number_registry
from .request_photos import sync_request_photos, write_request_photo_audit_events
from .statuses import completed_date_field, create_status_history, write_status_change_audit_event
from .tmc import (
    get_or_create_tmc_product,
    tmc_item_audit_rows,
    tmc_snapshot,
    write_tmc_item_audit_events,
)


TERMINAL_REQUEST_STATUSES = {NeedStatus.DONE, NeedStatus.REJECTED}


def audit_values_for_fields(values, fields):
    values = values or {}
    return {field: values.get(field) for field in fields if field in values}


def audit_values_without_fields(values, fields):
    excluded = set(fields)
    return {field: value for field, value in (values or {}).items() if field not in excluded}


def save_tmc_record(request, organ, table, instance, form, item_rows):
    """Persist a TMC request with items, photos, status history and audit events."""
    # ModelForm validation mutates the passed instance before this service is called.
    # Read the persisted object from DB so status-history and audit compare against
    # the real previous values, not the already-mutated in-memory instance.
    persisted_instance = instance.__class__.objects.get(pk=instance.pk) if instance and instance.pk else None
    old_values = tmc_snapshot(persisted_instance) if persisted_instance else None
    old_record_values = serialize_instance(persisted_instance) if persisted_instance else None
    old_status = persisted_instance.status if persisted_instance else None
    old_item_rows = tmc_item_audit_rows(persisted_instance) if persisted_instance else []
    selected_photo_ids = request.POST.getlist("attached_photos")
    is_create = instance is None

    with transaction.atomic():
        obj = form.save(commit=False)
        obj.territorial_organ = organ
        if obj.status in TERMINAL_REQUEST_STATUSES and not obj.due_date:
            obj.due_date = timezone.localdate()
        if not obj.pk:
            obj.created_by = request.user
        obj.updated_by = request.user
        obj.save()
        sync_request_number_registry(obj, table["department"])

        obj.items.all().delete()
        new_item_rows = []
        for row in item_rows:
            product, product_created = get_or_create_tmc_product(row["name"], row["unit"], row.get("product_id"))
            if product_created:
                write_audit(
                    AuditLog.Action.CREATE,
                    product,
                    old_values=None,
                    new_values={"audit_event": "tmc_product_created", **serialize_instance(product)},
                    request=request,
                )
            obj.items.create(product=product, name=product.name, quantity=row["quantity"], unit=row["unit"])
            new_item_rows.append({"name": product.name, "quantity": row["quantity"], "unit": row["unit"]})

        photo_changes = sync_request_photos(obj, selected_photo_ids, request.user)
        if is_create or old_status != obj.status:
            create_status_history(
                obj=obj,
                old_status=None if is_create else old_status,
                new_status=obj.status,
                completed_at=obj.due_date if obj.status in TERMINAL_REQUEST_STATUSES else None,
                changed_by=request.user,
                note="Создание заявки" if is_create else "Изменение статуса",
            )
        if not is_create:
            write_tmc_item_audit_events(obj, old_item_rows, new_item_rows, request)
        write_request_photo_audit_events(obj, photo_changes, request)

    new_values = tmc_snapshot(obj)
    new_record_values = serialize_instance(obj)
    status_changed = not is_create and old_status != obj.status
    if status_changed:
        status_fields = ("status", "due_date")
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values=audit_values_without_fields(old_record_values, status_fields),
            new_values=audit_values_without_fields(new_record_values, status_fields),
            request=request,
        )
        write_status_change_audit_event(
            obj,
            audit_values_for_fields(old_record_values, status_fields),
            audit_values_for_fields(new_record_values, status_fields),
            request,
        )
    else:
        write_audit(
            AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE,
            obj,
            old_values=old_values if is_create else old_record_values,
            new_values=new_values if is_create else new_record_values,
            request=request,
        )
    return obj


def save_record(request, organ, table, table_key, instance, form, selected_photo_ids, request_photo_tables, status_history_tables):
    """Persist a non-TMC record with number registry, photos, status history and audit events."""
    # ModelForm validation mutates the passed instance before this service is called.
    # Read the persisted object from DB so status-history and audit compare against
    # the real previous values, not the already-mutated in-memory instance.
    persisted_instance = instance.__class__.objects.get(pk=instance.pk) if instance and instance.pk else None
    old_values = serialize_instance(persisted_instance) if persisted_instance else None
    old_status = persisted_instance.status if persisted_instance and table_key in status_history_tables else None
    is_create = instance is None

    with transaction.atomic():
        obj = form.save(commit=False)
        obj.territorial_organ = organ
        completion_field = completed_date_field(table_key)
        if table_key in status_history_tables and obj.status in TERMINAL_REQUEST_STATUSES and not getattr(obj, completion_field):
            setattr(obj, completion_field, timezone.localdate())
        if not obj.pk:
            obj.created_by = request.user
        obj.updated_by = request.user
        obj.save()
        sync_request_number_registry(obj, table["department"])

        photo_changes = {"added": set(), "removed": set()}
        if table_key in request_photo_tables:
            photo_changes = sync_request_photos(obj, selected_photo_ids, request.user)
        if table_key in status_history_tables and (is_create or old_status != obj.status):
            create_status_history(
                obj=obj,
                old_status=None if is_create else old_status,
                new_status=obj.status,
                completed_at=getattr(obj, completion_field) if obj.status in TERMINAL_REQUEST_STATUSES else None,
                changed_by=request.user,
                note="Создание заявки" if is_create else "Изменение статуса",
            )
        if table_key in request_photo_tables:
            write_request_photo_audit_events(obj, photo_changes, request)

    new_values = serialize_instance(obj)
    status_changed = table_key in status_history_tables and not is_create and old_status != obj.status
    if status_changed:
        status_fields = ("status", completion_field)
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values=audit_values_without_fields(old_values, status_fields),
            new_values=audit_values_without_fields(new_values, status_fields),
            request=request,
        )
        write_status_change_audit_event(
            obj,
            audit_values_for_fields(old_values, status_fields),
            audit_values_for_fields(new_values, status_fields),
            request,
        )
    else:
        write_audit(
            AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE,
            obj,
            old_values=old_values,
            new_values=new_values,
            request=request,
        )
    return obj


def soft_delete_record(request, obj):
    old_values = serialize_instance(obj)
    with transaction.atomic():
        obj.is_deleted = True
        obj.updated_by = request.user
        obj.save(update_fields=["is_deleted", "updated_by", "updated_at"])
        remove_request_number_registry(obj)
        write_audit(
            AuditLog.Action.DELETE,
            obj,
            old_values=old_values,
            new_values=serialize_instance(obj),
            request=request,
        )
    return obj
