import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from PIL import Image, UnidentifiedImageError
from django.db import models
from django.db.models import Q


ALLOWED_PHOTO_FORMAT_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def detect_photo_content_mime_type(image):
    if not image:
        return ""

    file_obj = getattr(image, "file", image)
    original_position = None
    if hasattr(file_obj, "tell"):
        try:
            original_position = file_obj.tell()
        except (OSError, ValueError):
            original_position = None

    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        with Image.open(file_obj) as opened_image:
            image_format = (opened_image.format or "").upper()
            opened_image.verify()
        return ALLOWED_PHOTO_FORMAT_MIME_TYPES.get(image_format, "")
    except (UnidentifiedImageError, OSError, ValueError):
        return ""
    finally:
        if original_position is not None and hasattr(file_obj, "seek"):
            try:
                file_obj.seek(original_position)
            except (OSError, ValueError):
                pass


def validate_photo_content(image):
    if image and not detect_photo_content_mime_type(image):
        raise ValidationError("Файл должен быть изображением JPG, PNG или WEBP.")


def validate_photo_size(image):
    limit_mb = 8
    if image.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"Размер файла не должен превышать {limit_mb} МБ.")


class TerritorialOrgan(models.Model):
    name = models.CharField("наименование", max_length=255, unique=True)
    order_number = models.DecimalField("номер", max_digits=6, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])
    parent = models.ForeignKey("self", verbose_name="родитель", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        verbose_name = "территориальный орган"
        verbose_name_plural = "территориальные органы"
        ordering = ("order_number", "name")
        constraints = [models.CheckConstraint(condition=Q(order_number__gte=0), name="territorial_organ_order_non_negative")]
        indexes = [models.Index(fields=["is_active", "order_number"])]

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField("наименование", max_length=160, unique=True)
    slug = models.SlugField("код", max_length=80, unique=True)
    order_number = models.PositiveSmallIntegerField("порядок", default=0)
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        verbose_name = "отдел"
        verbose_name_plural = "отделы"
        ordering = ("order_number", "name")

    def __str__(self):
        return self.name


class TerritorialOrganPhotoFolder(models.Model):
    territorial_organ = models.ForeignKey(TerritorialOrgan, verbose_name="территориальный орган", on_delete=models.CASCADE, related_name="photo_folders")
    parent = models.ForeignKey("self", verbose_name="родительская папка", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField("наименование", max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_photo_folders")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="обновил", null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_photo_folders")
    created_department = models.ForeignKey("directory.Department", verbose_name="отдел автора", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_photo_folders")
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)
    is_deleted = models.BooleanField("удалено", default=False, db_index=True)

    class Meta:
        verbose_name = "папка фотографий"
        verbose_name_plural = "папки фотографий"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["territorial_organ", "name"], condition=Q(parent__isnull=True, is_deleted=False), name="unique_root_photo_folder_per_organ"),
            models.UniqueConstraint(fields=["territorial_organ", "parent", "name"], condition=Q(parent__isnull=False, is_deleted=False), name="unique_child_photo_folder_per_parent"),
        ]
        indexes = [models.Index(fields=["territorial_organ", "parent", "is_deleted", "name"])]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not self.parent_id:
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "Папка не может быть родительской для самой себя."})
        if self.parent.territorial_organ_id != self.territorial_organ_id:
            raise ValidationError({"parent": "Родительская папка должна относиться к этому же территориальному органу."})
        ancestor = self.parent
        while ancestor:
            if ancestor.pk == self.pk:
                raise ValidationError({"parent": "Папку нельзя поместить в ее вложенную папку."})
            ancestor = ancestor.parent


class TerritorialOrganPhoto(models.Model):
    territorial_organ = models.ForeignKey(TerritorialOrgan, verbose_name="территориальный орган", on_delete=models.CASCADE, related_name="photos")
    folder = models.ForeignKey(TerritorialOrganPhotoFolder, verbose_name="папка", null=True, blank=True, on_delete=models.SET_NULL, related_name="photos")
    image = models.ImageField(
        "изображение",
        upload_to="territorial_organs/%Y/%m/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_photo_size, validate_photo_content],
    )
    original_filename = models.CharField("имя файла", max_length=255, blank=True, db_index=True)
    file_size = models.PositiveBigIntegerField("размер файла, байт", default=0, editable=False, validators=[MinValueValidator(0)])
    mime_type = models.CharField("MIME-тип", max_length=100, blank=True, editable=False, db_index=True)
    description = models.TextField("описание", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_photos")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="обновил", null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_photos")
    created_department = models.ForeignKey("directory.Department", verbose_name="отдел автора", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_photos")
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)
    is_deleted = models.BooleanField("удалено", default=False, db_index=True)

    class Meta:
        verbose_name = "фотография территориального органа"
        verbose_name_plural = "фотографии территориальных органов"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["territorial_organ", "is_deleted"]), models.Index(fields=["territorial_organ", "folder", "is_deleted"])]

    def __str__(self):
        return f"{self.territorial_organ}: {self.created_at:%d.%m.%Y %H:%M}"

    def update_file_metadata(self):
        if not self.image:
            self.original_filename = ""
            self.file_size = 0
            self.mime_type = ""
            return

        self.original_filename = Path(self.image.name).name
        try:
            self.file_size = self.image.size or 0
        except (OSError, ValueError):
            self.file_size = 0

        content_type = detect_photo_content_mime_type(self.image)
        if not content_type:
            content_type = getattr(getattr(self.image, "file", None), "content_type", "")
        if not content_type:
            content_type = mimetypes.guess_type(self.image.name)[0] or ""
        self.mime_type = content_type[:100]

    def save(self, *args, **kwargs):
        self.update_file_metadata()
        super().save(*args, **kwargs)
