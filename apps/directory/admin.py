from django.contrib import admin
from django.utils.html import format_html

from .models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder


@admin.register(TerritorialOrgan)
class TerritorialOrganAdmin(admin.ModelAdmin):
    list_display = ("order_number", "name", "parent", "is_active")
    list_filter = ("is_active", "parent")
    search_fields = ("name", "description")
    ordering = ("order_number",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("order_number", "name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TerritorialOrganPhoto)
class TerritorialOrganPhotoAdmin(admin.ModelAdmin):
    list_display = ("preview", "territorial_organ", "folder", "file_size", "mime_type", "created_at", "created_by", "created_department", "is_deleted")
    list_filter = ("territorial_organ", "folder", "mime_type", "created_department", "created_by", "is_deleted")
    search_fields = ("description", "original_filename", "territorial_organ__name", "folder__name", "created_by__username", "created_by__last_name")
    readonly_fields = ("preview", "file_size", "mime_type", "created_at", "updated_at")

    class Media:
        css = {"all": ("css/admin.css",)}

    def preview(self, obj):
        if not obj.image:
            return "-"
        return format_html('<img src="{}" class="admin-preview-image">', obj.thumbnail_small_url)

    preview.short_description = "preview"


@admin.register(TerritorialOrganPhotoFolder)
class TerritorialOrganPhotoFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "territorial_organ", "created_at", "created_by", "created_department", "is_deleted")
    list_filter = ("territorial_organ", "parent", "created_department", "created_by", "is_deleted")
    search_fields = ("name", "parent__name", "territorial_organ__name", "created_by__username", "created_by__last_name")
    readonly_fields = ("created_at", "updated_at")
