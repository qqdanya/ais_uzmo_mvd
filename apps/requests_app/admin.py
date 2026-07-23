from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from apps.audit.admin_audit import AuditedModelAdminMixin

from . import models


class RequestAdmin(AuditedModelAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "territorial_organ", "created_at", "updated_at", "is_deleted")
    list_filter = ("territorial_organ", "is_deleted", "created_at")
    search_fields = ("comment", "territorial_organ__name")
    readonly_fields = ("created_at", "updated_at")


class TmcRequestItemInline(admin.TabularInline):
    model = models.TmcRequestItem
    extra = 1


@admin.register(models.TmcProduct)
class TmcProductAdmin(AuditedModelAdminMixin, admin.ModelAdmin):
    list_display = ("name", "unit", "is_active", "updated_at")
    list_filter = ("is_active", "unit")
    search_fields = ("name", "normalized_name")
    readonly_fields = ("normalized_name", "created_at", "updated_at")


class RequestStatusHistoryInline(GenericTabularInline):
    model = models.RequestStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("old_status", "new_status", "completed_at", "changed_by", "changed_at", "note")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.TmcRequest)
class TmcRequestAdmin(RequestAdmin):
    inlines = [TmcRequestItemInline, RequestStatusHistoryInline]
    list_display = ("__str__", "territorial_organ", "request_date", "status", "created_at", "is_deleted")
    list_filter = ("territorial_organ", "status", "is_deleted", "request_date")
    search_fields = ("request_number", "comment", "items__name", "territorial_organ__name")


for model in [
    models.VehicleInventory,
    models.VehicleRepairRequest,
    models.VehicleFuelRequest,
    models.FireExtinguisher,
    models.FireAlarm,
    models.SecurityAlarm,
    models.FireDepartmentRequest,
    models.AntiTerrorMeasure,
    models.CitsiziEquipment,
    models.ServiceHousing,
    models.BuildingRepairRequest,
]:
    admin.site.register(model, RequestAdmin)


@admin.register(models.RequestStatusHistory)
class RequestStatusHistoryAdmin(AuditedModelAdminMixin, admin.ModelAdmin):
    list_display = ("request", "old_status", "new_status", "completed_at", "changed_by", "changed_at")
    list_filter = ("content_type", "new_status", "changed_at")
    search_fields = ("note",)
    readonly_fields = ("content_type", "object_id", "old_status", "new_status", "completed_at", "changed_by", "changed_at", "note")


@admin.register(models.RequestResponse)
class RequestResponseAdmin(admin.ModelAdmin):
    """Read-only registry; changes belong to the request workflow and its audit."""

    list_display = (
        "response_number",
        "response_date",
        "request",
        "created_by",
        "created_at",
    )
    list_filter = ("response_date", "content_type", "created_at")
    search_fields = ("response_number", "normalized_response_number", "note", "=object_id")
    readonly_fields = (
        "content_type",
        "object_id",
        "request",
        "response_number",
        "normalized_response_number",
        "response_date",
        "note",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.RequestPhotoLink)
class RequestPhotoLinkAdmin(AuditedModelAdminMixin, admin.ModelAdmin):
    list_display = ("request", "photo", "territorial_organ", "created_by", "created_at")
    list_filter = ("territorial_organ", "content_type", "created_at")
    search_fields = ("photo__description", "photo__original_filename", "territorial_organ__name")
    readonly_fields = ("created_at",)


@admin.register(models.RequestNumberRegistry)
class RequestNumberRegistryAdmin(AuditedModelAdminMixin, admin.ModelAdmin):
    list_display = ("request_number", "territorial_organ", "department", "request", "updated_at")
    list_filter = ("territorial_organ", "department", "content_type")
    search_fields = ("request_number", "territorial_organ__name")
    readonly_fields = ("normalized_request_number", "content_type", "object_id", "created_at", "updated_at")
