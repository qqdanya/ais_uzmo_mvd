from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model_name", "object_repr", "territorial_organ", "ip_address")
    list_filter = ("action", "model_name", "territorial_organ", "created_at")
    search_fields = ("user__username", "object_repr", "model_name", "ip_address")
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Записи журнала действий доступны только для чтения.")

    def delete_model(self, request, obj):
        raise PermissionDenied("Записи журнала действий нельзя удалять.")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Записи журнала действий нельзя удалять.")
