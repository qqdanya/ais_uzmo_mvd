import mimetypes
from hashlib import blake2b
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator, MinValueValidator
from PIL import Image, ImageOps, UnidentifiedImageError
from django.db import models
from django.db.models import Q


ALLOWED_PHOTO_FORMAT_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}

PHOTO_THUMBNAIL_SIZES = {
    "small": (160, 160),
    "medium": (640, 480),
}
PHOTO_THUMBNAIL_FIELDS = {
    "small": "thumbnail_small",
    "medium": "thumbnail_medium",
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
    thumbnail_small = models.ImageField("миниатюра 160px", upload_to="", blank=True, editable=False)
    thumbnail_medium = models.ImageField("миниатюра 640px", upload_to="", blank=True, editable=False)
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

    @property
    def thumbnail_small_url(self):
        return self._preview_url("thumbnail_small")

    @property
    def thumbnail_medium_url(self):
        return self._preview_url("thumbnail_medium")

    def _preview_url(self, field_name):
        field = getattr(self, field_name)
        if field:
            try:
                return field.url
            except ValueError:
                pass
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return ""

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

    def thumbnail_storage_name(self, kind):
        source = Path(self.image.name)
        digest = blake2b(f"{self.pk}:{self.image.name}:{kind}".encode("utf-8"), digest_size=8).hexdigest()
        stem = source.stem[:80] or f"photo-{self.pk}"
        return f"territorial_organs/thumbnails/{kind}/{stem}-{digest}.jpg"

    def _build_thumbnail_content(self, kind):
        size = PHOTO_THUMBNAIL_SIZES[kind]
        self.image.open("rb")
        try:
            with Image.open(self.image) as source_image:
                image = ImageOps.exif_transpose(source_image)
                image.thumbnail(size, Image.Resampling.LANCZOS)
                if image.mode not in {"RGB", "L"}:
                    background = Image.new("RGB", image.size, "white")
                    if image.mode in {"RGBA", "LA"}:
                        background.paste(image, mask=image.getchannel("A"))
                    else:
                        background.paste(image.convert("RGB"))
                    image = background
                elif image.mode != "RGB":
                    image = image.convert("RGB")
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=82, optimize=True, progressive=True)
                return ContentFile(buffer.getvalue())
        finally:
            self.image.close()

    def ensure_thumbnails(self, *, force=False, save=True):
        if not self.pk or not self.image:
            return False
        changed = False
        for kind, field_name in PHOTO_THUMBNAIL_FIELDS.items():
            field = getattr(self, field_name)
            if field and not force:
                continue
            old_name = field.name if field else ""
            if old_name:
                field.storage.delete(old_name)
            try:
                content = self._build_thumbnail_content(kind)
            except (OSError, ValueError, UnidentifiedImageError):
                continue
            field.save(self.thumbnail_storage_name(kind), content, save=False)
            changed = True
        if changed and save:
            type(self).objects.filter(pk=self.pk).update(
                thumbnail_small=self.thumbnail_small.name,
                thumbnail_medium=self.thumbnail_medium.name,
            )
        return changed

    def delete_thumbnail_files(self):
        for field_name in PHOTO_THUMBNAIL_FIELDS.values():
            field = getattr(self, field_name)
            if field:
                field.delete(save=False)

    def delete_files(self, *, include_original=False):
        self.delete_thumbnail_files()
        if include_original and self.image:
            self.image.delete(save=False)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        should_refresh_thumbnails = update_fields is None or "image" in set(update_fields)
        old_image_name = ""
        if self.pk and should_refresh_thumbnails:
            old_photo = type(self).objects.filter(pk=self.pk).only("image", "thumbnail_small", "thumbnail_medium").first()
            if old_photo:
                old_image_name = old_photo.image.name

        self.update_file_metadata()
        super().save(*args, **kwargs)

        if self.image and should_refresh_thumbnails:
            image_changed = bool(old_image_name and old_image_name != self.image.name)
            needs_thumbnails = image_changed or not self.thumbnail_small or not self.thumbnail_medium
            if needs_thumbnails:
                self.ensure_thumbnails(force=image_changed, save=True)

    def delete(self, *args, **kwargs):
        self.delete_files(include_original=True)
        super().delete(*args, **kwargs)
