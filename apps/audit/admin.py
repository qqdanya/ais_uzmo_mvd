from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model_name", "object_repr", "territorial_organ", "ip_address")
    list_filter = ("action", "model_name", "territorial_organ", "created_at")
    search_fields = ("user__username", "object_repr", "model_name", "ip_address")
    readonly_fields = [field.name for field in AuditLog._meta.fields]
