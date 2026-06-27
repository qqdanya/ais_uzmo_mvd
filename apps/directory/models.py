from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q


def validate_photo_size(image):
    limit_mb = 8
    if image.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"Размер файла не должен превышать {limit_mb} МБ.")


class TerritorialOrgan(models.Model):
    name = models.CharField("наименование", max_length=255, unique=True)
    order_number = models.DecimalField("номер", max_digits=6, decimal_places=2, db_index=True)
    parent = models.ForeignKey("self", verbose_name="родитель", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        verbose_name = "территориальный орган"
        verbose_name_plural = "территориальные органы"
        ordering = ("order_number", "name")
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
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "папка фотографий"
        verbose_name_plural = "папки фотографий"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["territorial_organ", "name"], condition=Q(parent__isnull=True), name="unique_root_photo_folder_per_organ"),
            models.UniqueConstraint(fields=["territorial_organ", "parent", "name"], condition=Q(parent__isnull=False), name="unique_child_photo_folder_per_parent"),
        ]
        indexes = [models.Index(fields=["territorial_organ", "parent", "name"])]

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
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_photo_size],
    )
    original_filename = models.CharField("имя файла", max_length=255, blank=True, db_index=True)
    description = models.TextField("описание", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_photos")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="обновил", null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_photos")
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

    def save(self, *args, **kwargs):
        if self.image:
            self.original_filename = Path(self.image.name).name
        super().save(*args, **kwargs)
