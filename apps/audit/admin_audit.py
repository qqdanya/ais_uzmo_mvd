"""Audit support for writes made through Django's built-in admin site.

The application's normal views write their own, more specific events.  Django
admin is a separate write path, so ModelAdmin hooks are used here instead of
signals.  That keeps request metadata available and avoids double logging the
normal application views.
"""

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models.fields.files import FieldFile

from .models import AuditLog
from .utils import client_ip, has_meaningful_changes, object_message


SENSITIVE_FIELD_NAMES = {
    "activation_code",
    "password",
}

USER_EVENT_TYPES = {
    AuditLog.Action.CREATE: AuditLog.EventType.EMPLOYEE_CREATED,
    AuditLog.Action.UPDATE: AuditLog.EventType.EMPLOYEE_PERMISSIONS,
    AuditLog.Action.DELETE: AuditLog.EventType.EMPLOYEE_DELETED,
}


def _admin_event_type(action, model_name):
    if model_name == "User":
        return USER_EVENT_TYPES.get(action, "")
    if model_name == "RequestPhotoLink":
        return {
            AuditLog.Action.CREATE: AuditLog.EventType.PHOTOS_ATTACHED,
            AuditLog.Action.DELETE: AuditLog.EventType.PHOTOS_DETACHED,
        }.get(action, "")
    if action != AuditLog.Action.DELETE:
        return ""
    return {
        "TerritorialOrganPhoto": AuditLog.EventType.PHOTO_PURGED,
        "TerritorialOrganPhotoFolder": AuditLog.EventType.FOLDER_PURGED,
    }.get(model_name, AuditLog.EventType.RECORD_PURGED)


def _json_value(value):
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID, Path)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sorted_names(queryset):
    return sorted((str(item) for item in queryset), key=str.casefold)


def _related_profile(user):
    try:
        return user.profile
    except (AttributeError, ObjectDoesNotExist):
        return None


def user_audit_snapshot(user):
    """Return a useful employee snapshot without password or activation code."""
    profile = _related_profile(user)
    values = {
        "username": user.username,
        "last_name": user.last_name,
        "first_name": user.first_name,
        "middle_name": getattr(profile, "middle_name", ""),
        "role": getattr(profile, "role", ""),
        "allowed_departments": _sorted_names(profile.allowed_departments.all()) if profile else [],
        "allowed_organs": _sorted_names(profile.allowed_organs.all()) if profile else [],
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "activation_status": "activated" if user.has_usable_password() else "needs_activation",
        # These keys deliberately do not use the real ManyToMany field names.
        # The journal's generic formatter treats real relation fields as one
        # foreign key; display-only keys safely support several values.
        "django_groups": _sorted_names(user.groups.all()),
        "django_permissions": sorted(
            (
                f"{permission.content_type.app_label}.{permission.codename}"
                for permission in user.user_permissions.select_related("content_type")
            ),
            key=str.casefold,
        ),
    }
    return values


def model_audit_snapshot(instance):
    if instance.__class__ is get_user_model():
        return user_audit_snapshot(instance)

    values = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in SENSITIVE_FIELD_NAMES:
            continue
        if getattr(field, "is_relation", False):
            value = getattr(instance, field.attname, None)
        else:
            value = field.value_from_object(instance)
        values[field.name] = _json_value(value)
    if instance.__class__.__name__ == "TerritorialOrganPhotoFolder":
        values.update(_folder_photo_snapshot(instance))
    elif instance.__class__.__name__ == "RequestPhotoLink":
        values.update(_linked_photo_snapshot(instance))
    return values


def _folder_tree_ids(folder):
    from apps.directory.models import TerritorialOrganPhotoFolder

    children_by_parent = {}
    rows = TerritorialOrganPhotoFolder.objects.filter(
        territorial_organ_id=folder.territorial_organ_id,
    ).values_list("pk", "parent_id")
    for pk, parent_id in rows:
        children_by_parent.setdefault(parent_id, []).append(pk)

    folder_ids = []
    pending = [folder.pk]
    seen = set()
    while pending:
        folder_id = pending.pop()
        if folder_id in seen:
            continue
        seen.add(folder_id)
        folder_ids.append(folder_id)
        pending.extend(children_by_parent.get(folder_id, ()))
    return folder_ids


def _folder_photo_snapshot(folder):
    from apps.directory.models import TerritorialOrganPhoto
    from apps.requests_app.services.request_photos import photo_snapshot_for_audit

    photos = TerritorialOrganPhoto.objects.filter(
        territorial_organ_id=folder.territorial_organ_id,
        folder_id__in=_folder_tree_ids(folder),
    )
    return photo_snapshot_for_audit(photos=photos)


def _linked_photo_snapshot(link):
    from apps.requests_app.services.request_photos import photo_snapshot_for_audit

    return photo_snapshot_for_audit([link.photo_id] if link.photo_id else [])


def _employee_object_repr(user):
    profile = _related_profile(user)
    if profile:
        return profile.display_name
    return user.get_full_name().strip() or user.get_username()


def _territorial_organ_id(instance):
    organ_id = getattr(instance, "territorial_organ_id", None)
    if organ_id:
        return organ_id
    if instance.__class__.__name__ == "TerritorialOrgan":
        return instance.pk

    try:
        linked_request = getattr(instance, "request", None)
    except (AttributeError, ObjectDoesNotExist):
        linked_request = None
    return getattr(linked_request, "territorial_organ_id", None)


def capture_admin_object(instance):
    if instance.__class__ is get_user_model():
        object_repr = _employee_object_repr(instance)
    else:
        object_repr = object_message("", instance)
    return {
        "model_name": instance.__class__.__name__,
        "object_id": str(instance.pk) if instance.pk is not None else "",
        "object_repr": str(object_repr)[:255],
        "territorial_organ_id": _territorial_organ_id(instance),
        "values": model_audit_snapshot(instance),
    }


def _operation_id(request):
    value = getattr(request, "_audit_operation_id", "")
    if not value:
        value = str(uuid4())
        request._audit_operation_id = value
    return value


def _existing_actor_id(request):
    actor = getattr(request, "user", None)
    actor_id = getattr(actor, "pk", None)
    if not actor_id:
        return None
    return actor_id if get_user_model()._default_manager.filter(pk=actor_id).exists() else None


def _existing_organ_id(organ_id):
    if not organ_id:
        return None
    from apps.directory.models import TerritorialOrgan

    return organ_id if TerritorialOrgan.objects.filter(pk=organ_id).exists() else None


def write_admin_audit(
    request,
    action,
    *,
    instance=None,
    captured=None,
    old_values=None,
    new_values=None,
    event_type=None,
):
    """Write one admin event, including metadata unavailable to model signals."""
    if captured is None:
        captured = capture_admin_object(instance)
    model_name = captured["model_name"]

    if action == AuditLog.Action.UPDATE and not has_meaningful_changes(instance, old_values, new_values):
        return None

    if event_type is None:
        event_type = _admin_event_type(action, model_name)
    if event_type:
        new_values = {"audit_event": event_type, **(new_values or {})}

    return AuditLog.objects.create(
        user_id=_existing_actor_id(request),
        action=action,
        event_type=event_type,
        operation_id=_operation_id(request),
        model_name=model_name,
        object_id=captured["object_id"],
        object_repr=captured["object_repr"],
        old_values=old_values,
        new_values=new_values,
        territorial_organ_id=_existing_organ_id(captured.get("territorial_organ_id")),
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


class AuditedModelAdminMixin:
    """Log ModelAdmin creates, updates, deletes, and editable inline rows."""

    audit_defer_save_related = False
    audit_inline_models = True

    def save_model(self, request, obj, form, change):
        old_values = None
        if change and obj.pk:
            stored = self.model._default_manager.filter(pk=obj.pk).first()
            if stored is not None:
                old_values = model_audit_snapshot(stored)
        form._domain_audit_old_values = old_values
        form._domain_audit_is_change = change
        form._domain_audit_written = False
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not self.audit_defer_save_related:
            self.finalize_admin_audit(request, form)

    def finalize_admin_audit(self, request, form):
        if getattr(form, "_domain_audit_written", False):
            return None
        form._domain_audit_written = True

        obj = form.instance
        stored = self.model._default_manager.filter(pk=obj.pk).first()
        if stored is None:
            return None
        new_values = model_audit_snapshot(stored)
        old_values = getattr(form, "_domain_audit_old_values", None)
        action = (
            AuditLog.Action.UPDATE
            if getattr(form, "_domain_audit_is_change", False)
            else AuditLog.Action.CREATE
        )
        return write_admin_audit(
            request,
            action,
            instance=stored,
            old_values=old_values,
            new_values=new_values,
        )

    def save_formset(self, request, form, formset, change):
        if not self.audit_inline_models:
            return super().save_formset(request, form, formset, change)

        old_by_pk = {}
        for inline_form in formset.forms:
            instance = inline_form.instance
            original_pk = instance.pk
            if original_pk is None:
                continue
            stored = instance.__class__._default_manager.filter(pk=original_pk).first()
            if stored is not None:
                old_by_pk[str(original_pk)] = capture_admin_object(stored)
                instance._domain_audit_original_pk = original_pk

        result = super().save_formset(request, form, formset, change)

        for instance in getattr(formset, "new_objects", []):
            stored = instance.__class__._default_manager.filter(pk=instance.pk).first()
            if stored is not None:
                write_admin_audit(
                    request,
                    AuditLog.Action.CREATE,
                    instance=stored,
                    new_values=model_audit_snapshot(stored),
                )

        for instance, _changed_fields in getattr(formset, "changed_objects", []):
            original_pk = getattr(instance, "_domain_audit_original_pk", instance.pk)
            captured = old_by_pk.get(str(original_pk))
            stored = instance.__class__._default_manager.filter(pk=instance.pk).first()
            if captured is not None and stored is not None:
                write_admin_audit(
                    request,
                    AuditLog.Action.UPDATE,
                    instance=stored,
                    old_values=captured["values"],
                    new_values=model_audit_snapshot(stored),
                )

        for instance in getattr(formset, "deleted_objects", []):
            original_pk = getattr(instance, "_domain_audit_original_pk", instance.pk)
            captured = old_by_pk.get(str(original_pk))
            if captured is not None:
                write_admin_audit(
                    request,
                    AuditLog.Action.DELETE,
                    captured=captured,
                    old_values=captured["values"],
                )
        return result

    def delete_model(self, request, obj):
        captured = capture_admin_object(obj)
        super().delete_model(request, obj)
        write_admin_audit(
            request,
            AuditLog.Action.DELETE,
            captured=captured,
            old_values=captured["values"],
        )

    def delete_queryset(self, request, queryset):
        captured_objects = [capture_admin_object(obj) for obj in queryset.iterator()]
        super().delete_queryset(request, queryset)
        for captured in captured_objects:
            write_admin_audit(
                request,
                AuditLog.Action.DELETE,
                captured=captured,
                old_values=captured["values"],
            )
