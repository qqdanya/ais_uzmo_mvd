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


def save_tmc_record(request, organ, table, instance, form, item_rows):
    """Persist a TMC request with items, photos, status history and audit events."""
    # ModelForm validation mutates the passed instance before this service is called.
    # Read the persisted object from DB so status-history and audit compare against
    # the real previous values, not the already-mutated in-memory instance.
    persisted_instance = instance.__class__.objects.get(pk=instance.pk) if instance and instance.pk else None
    old_values = tmc_snapshot(persisted_instance) if persisted_instance else None
    old_status = persisted_instance.status if persisted_instance else None
    old_item_rows = tmc_item_audit_rows(persisted_instance) if persisted_instance else []
    selected_photo_ids = request.POST.getlist("attached_photos")
    is_create = instance is None

    with transaction.atomic():
        obj = form.save(commit=False)
        obj.territorial_organ = organ
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
                completed_at=obj.due_date if obj.status == NeedStatus.DONE else None,
                changed_by=request.user,
                note="Создание заявки" if is_create else "Изменение статуса",
            )
        if not is_create and old_status != obj.status:
            write_status_change_audit_event(obj, old_status, obj.status, request)
        if not is_create:
            write_tmc_item_audit_events(obj, old_item_rows, new_item_rows, request)
        write_request_photo_audit_events(obj, photo_changes, request)

    write_audit(
        AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE,
        obj,
        old_values=old_values,
        new_values=tmc_snapshot(obj),
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
        if table_key in status_history_tables and obj.status == NeedStatus.DONE and not getattr(obj, completion_field):
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
                completed_at=getattr(obj, completion_field) if obj.status == NeedStatus.DONE else None,
                changed_by=request.user,
                note="Создание заявки" if is_create else "Изменение статуса",
            )
        if table_key in status_history_tables and not is_create and old_status != obj.status:
            write_status_change_audit_event(obj, old_status, obj.status, request)
        if table_key in request_photo_tables:
            write_request_photo_audit_events(obj, photo_changes, request)

    write_audit(
        AuditLog.Action.UPDATE if instance else AuditLog.Action.CREATE,
        obj,
        old_values=old_values,
        new_values=serialize_instance(obj),
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
