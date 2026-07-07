from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
import re


def normalize_product_name(value):
    value = (value or "").replace("ё", "е").replace("Ё", "Е").casefold()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_request_number(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    return value.replace("ё", "е").replace("Ё", "Е").casefold()


class TrackableRequest(models.Model):
    territorial_organ = models.ForeignKey("directory.TerritorialOrgan", verbose_name="территориальный орган", on_delete=models.PROTECT, related_name="%(class)s_items", db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)s_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="обновил", null=True, blank=True, on_delete=models.SET_NULL, related_name="%(class)s_updated")
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)
    is_deleted = models.BooleanField("удалено", default=False, db_index=True)
    comment = models.TextField("описание", blank=True)

    class Meta:
        abstract = True


class NeedStatus(models.TextChoices):
    IN_WORK = "in_work", "В работе"
    DONE = "done", "Исполнена"
    REJECTED = "rejected", "Отклонена"


ACTIVE_NEED_STATUS_CHOICES = (
    (NeedStatus.IN_WORK, NeedStatus.IN_WORK.label),
    (NeedStatus.DONE, NeedStatus.DONE.label),
    (NeedStatus.REJECTED, NeedStatus.REJECTED.label),
)


def validate_lte(errors, field, value, limit, message):
    if value is not None and limit is not None and value > limit:
        errors[field] = message


class TmcRequest(TrackableRequest):
    request_number = models.CharField("номер заявки", max_length=80)
    request_date = models.DateField("дата заявки")
    status = models.CharField("исполнение заявки", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    due_date = models.DateField("дата исполнения", null=True, blank=True)

    class Meta:
        verbose_name = "заявка ТМЦ"
        verbose_name_plural = "Заявки ТМЦ"
        ordering = ("-request_date", "-created_at")
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    @property
    def items_summary(self):
        return "; ".join(str(item) for item in self.items.all())

    def __str__(self):
        return f"Заявка ТМЦ № {self.request_number}"


class TmcRequestItem(models.Model):
    request = models.ForeignKey(TmcRequest, verbose_name="заявка", on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("TmcProduct", verbose_name="товар", null=True, blank=True, on_delete=models.PROTECT, related_name="request_items")
    name = models.CharField("наименование", max_length=180)
    quantity = models.PositiveIntegerField("количество", validators=[MinValueValidator(1)])
    unit = models.CharField("единица измерения", max_length=40, default="шт.")

    class Meta:
        verbose_name = "позиция заявки ТМЦ"
        verbose_name_plural = "Позиции заявки ТМЦ"
        ordering = ("id",)

    def __str__(self):
        return f"{self.name} {self.quantity} {self.unit}"


class TmcProduct(models.Model):
    name = models.CharField("наименование", max_length=180)
    normalized_name = models.CharField("нормализованное наименование", max_length=180, unique=True, db_index=True)
    unit = models.CharField("единица измерения", max_length=40, default="шт.")
    is_active = models.BooleanField("активен", default=True, db_index=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        verbose_name = "товар ТМЦ"
        verbose_name_plural = "Справочник товаров ТМЦ"
        ordering = ("name",)

    def save(self, *args, **kwargs):
        self.name = re.sub(r"\s+", " ", (self.name or "").strip())
        self.normalized_name = normalize_product_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class RequestNumberRegistry(models.Model):
    territorial_organ = models.ForeignKey("directory.TerritorialOrgan", verbose_name="территориальный орган", on_delete=models.CASCADE, related_name="request_number_registry")
    department = models.SlugField("отдел", max_length=80, db_index=True)
    request_number = models.CharField("номер заявки", max_length=80)
    normalized_request_number = models.CharField("нормализованный номер", max_length=80, db_index=True)
    content_type = models.ForeignKey(ContentType, verbose_name="тип заявки", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField("ID заявки")
    request = GenericForeignKey("content_type", "object_id")
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        verbose_name = "номер заявки"
        verbose_name_plural = "Реестр номеров заявок"
        ordering = ("territorial_organ__name", "department", "request_number")
        constraints = [
            models.UniqueConstraint(
                fields=["territorial_organ", "department", "normalized_request_number"],
                name="unique_request_number_per_organ_department",
            ),
            models.UniqueConstraint(fields=["content_type", "object_id"], name="unique_request_number_registry_object"),
        ]
        indexes = [
            models.Index(fields=["territorial_organ", "department", "normalized_request_number"], name="requests_ap_territo_1edceb_idx"),
            models.Index(fields=["content_type", "object_id"], name="requests_ap_content_39b5b7_idx"),
        ]

    def save(self, *args, **kwargs):
        self.request_number = re.sub(r"\s+", " ", str(self.request_number or "").strip())
        self.normalized_request_number = normalize_request_number(self.request_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.territorial_organ} / {self.department} / № {self.request_number}"


class RequestStatusHistory(models.Model):
    content_type = models.ForeignKey(ContentType, verbose_name="тип заявки", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField("ID заявки")
    request = GenericForeignKey("content_type", "object_id")
    old_status = models.CharField("предыдущий статус", max_length=20, choices=NeedStatus.choices, null=True, blank=True)
    new_status = models.CharField("новый статус", max_length=20, choices=NeedStatus.choices)
    completed_at = models.DateField("дата исполнения", null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="изменил", null=True, blank=True, on_delete=models.SET_NULL, related_name="request_status_changes")
    changed_at = models.DateTimeField("дата изменения", auto_now_add=True, db_index=True)
    note = models.CharField("примечание", max_length=255, blank=True)

    class Meta:
        verbose_name = "изменение статуса заявки"
        verbose_name_plural = "История статусов заявок"
        ordering = ("-changed_at", "-id")
        indexes = [models.Index(fields=["content_type", "object_id", "-changed_at"])]

    def __str__(self):
        old_status = self.get_old_status_display() if self.old_status else "Создана"
        return f"{old_status} -> {self.get_new_status_display()}"


class RequestPhotoLink(models.Model):
    territorial_organ = models.ForeignKey("directory.TerritorialOrgan", verbose_name="территориальный орган", on_delete=models.CASCADE, related_name="request_photo_links")
    photo = models.ForeignKey("directory.TerritorialOrganPhoto", verbose_name="фотография", on_delete=models.CASCADE, related_name="request_links")
    content_type = models.ForeignKey(ContentType, verbose_name="тип заявки", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField("ID заявки")
    request = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_request_photo_links")
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "связь заявки с фотографией"
        verbose_name_plural = "Связи заявок с фотографиями"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=["photo", "content_type", "object_id"], name="unique_request_photo_link"),
        ]
        indexes = [
            models.Index(fields=["territorial_organ", "content_type", "object_id"]),
            models.Index(fields=["photo", "content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.request} - {self.photo}"


class VehicleInventory(TrackableRequest):
    state_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    required_count = models.PositiveIntegerField("положено", validators=[MinValueValidator(0)])
    available_count = models.PositiveIntegerField("наличие", validators=[MinValueValidator(0)])
    broken_count = models.PositiveIntegerField("неисправно", validators=[MinValueValidator(0)])
    writeoff_count = models.PositiveIntegerField("подлежит списанию (передаче в Росимущество)", validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "автотранспорт"
        verbose_name_plural = "Автотранспорт"
        ordering = ("-state_date", "-created_at")

    def __str__(self):
        return f"Автотранспорт: {self.available_count}/{self.required_count}"

    def clean(self):
        errors = {}
        validate_lte(errors, "available_count", self.available_count, self.required_count, "Наличие не может быть больше значения «положено».")
        validate_lte(errors, "broken_count", self.broken_count, self.available_count, "Неисправных единиц не может быть больше наличия.")
        validate_lte(errors, "writeoff_count", self.writeoff_count, self.required_count, "К списанию не может быть больше значения «положено».")
        if errors:
            raise ValidationError(errors)


class VehicleRepairRequest(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата")
    status = models.CharField("исполнение заявки", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    completed_at = models.DateField("дата исполнения заявки", null=True, blank=True)

    class Meta:
        verbose_name = "заявка на ремонт автотранспорта"
        verbose_name_plural = "Заявки на ремонт автотранспорта"
        ordering = ("-request_date",)
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    def __str__(self):
        return f"Заявка на ремонт № {self.request_number}"


class VehicleFuelRequest(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата")
    status = models.CharField("исполнение заявки", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    completed_at = models.DateField("дата исполнения заявки", null=True, blank=True)

    class Meta:
        verbose_name = "заявка на ГСМ"
        verbose_name_plural = "Заявки на ГСМ"
        ordering = ("-request_date",)
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    def __str__(self):
        return f"Заявка на ГСМ № {self.request_number}"


class FireExtinguisher(TrackableRequest):
    state_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    required_count = models.PositiveIntegerField("положено", validators=[MinValueValidator(0)])
    available_count = models.PositiveIntegerField("наличие", validators=[MinValueValidator(0)])
    expiry_date = models.DateField("срок годности (эксплуатации)", db_index=True)
    writeoff_count = models.PositiveIntegerField("подлежит списанию", validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "огнетушитель"
        verbose_name_plural = "Огнетушители"
        ordering = ("-state_date", "expiry_date", "-created_at")

    def __str__(self):
        return f"Огнетушители: {self.available_count}/{self.required_count}"

    def clean(self):
        errors = {}
        validate_lte(errors, "available_count", self.available_count, self.required_count, "Наличие не может быть больше значения «положено».")
        validate_lte(errors, "writeoff_count", self.writeoff_count, self.required_count, "К списанию не может быть больше значения «положено».")
        if errors:
            raise ValidationError(errors)


class FireAlarm(TrackableRequest):
    state_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    required_objects = models.PositiveIntegerField("подлежит оборудованию ПС", validators=[MinValueValidator(0)])
    equipped_objects = models.PositiveIntegerField("оборудовано ПС объектов", validators=[MinValueValidator(0)])
    broken_objects = models.PositiveIntegerField("объектов с неисправной ПС", validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "пожарная сигнализация"
        verbose_name_plural = "Пожарная сигнализация"
        ordering = ("-state_date", "-created_at")

    def __str__(self):
        return f"Пожарная сигнализация: {self.equipped_objects}/{self.required_objects}"

    def clean(self):
        errors = {}
        validate_lte(errors, "equipped_objects", self.equipped_objects, self.required_objects, "Оборудованных объектов не может быть больше объектов, подлежащих оборудованию.")
        validate_lte(errors, "broken_objects", self.broken_objects, self.equipped_objects, "Неисправных объектов не может быть больше оборудованных объектов.")
        if errors:
            raise ValidationError(errors)


class SecurityAlarm(TrackableRequest):
    state_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    required_objects = models.PositiveIntegerField("подлежит оборудованию ОС", validators=[MinValueValidator(0)])
    equipped_objects = models.PositiveIntegerField("оборудовано ОС объектов", validators=[MinValueValidator(0)])
    broken_objects = models.PositiveIntegerField("объектов с неисправной ОС", validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "охранная сигнализация"
        verbose_name_plural = "Охранная сигнализация"
        ordering = ("-state_date", "-created_at")

    def __str__(self):
        return f"Охранная сигнализация: {self.equipped_objects}/{self.required_objects}"

    def clean(self):
        errors = {}
        validate_lte(errors, "equipped_objects", self.equipped_objects, self.required_objects, "Оборудованных объектов не может быть больше объектов, подлежащих оборудованию.")
        validate_lte(errors, "broken_objects", self.broken_objects, self.equipped_objects, "Неисправных объектов не может быть больше оборудованных объектов.")
        if errors:
            raise ValidationError(errors)


class FireDepartmentRequest(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата")
    status = models.CharField("исполнение заявки", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    completed_at = models.DateField("дата исполнения заявки", null=True, blank=True)

    class Meta:
        verbose_name = "заявка пожарной безопасности"
        verbose_name_plural = "Заявки пожарной безопасности"
        ordering = ("-request_date",)
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    def __str__(self):
        return f"Заявка № {self.request_number}"


class AntiTerrorMeasure(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    status = models.CharField("исполнение", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    completed_at = models.DateField("дата исполнения заявки", null=True, blank=True)

    class Meta:
        verbose_name = "антитеррористическая укрепленность"
        verbose_name_plural = "Антитеррористическая укрепленность"
        ordering = ("-request_date", "-created_at")
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    def __str__(self):
        return f"Акт обследования № {self.request_number}" if self.request_number else "Акт обследования"


class EquipmentType(models.TextChoices):
    COMMUNICATION = "communication", "Средства связи"
    ORGANIZATIONAL = "organizational", "Организационная техника"
    COMPUTING = "computing", "Вычислительная техника"
    SPECIAL = "special", "Специальная техника"
    VIDEO = "video", "Видеонаблюдение"
    SOUND_ALERT = "sound_alert", "Система звукового оповещения"


class CitsiziEquipment(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    equipment_type = models.CharField("тип техники", max_length=30, choices=EquipmentType.choices, db_index=True)
    quantity = models.PositiveIntegerField("количество", validators=[MinValueValidator(1)])
    status = models.CharField("исполнение", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    due_date = models.DateField("дата исполнения заявки", null=True, blank=True)

    class Meta:
        verbose_name = "заявка ЦИТСиЗИ"
        verbose_name_plural = "По линии ЦИТСиЗИ"
        ordering = ("-request_date", "-created_at")
        indexes = [models.Index(fields=["territorial_organ", "equipment_type"])]

    def __str__(self):
        return f"Заявка № {self.request_number}" if self.request_number else "Заявка ЦИТСиЗИ"


class ServiceHousing(TrackableRequest):
    state_date = models.DateField("дата", default=timezone.localdate, db_index=True)
    total_count = models.PositiveIntegerField("общее количество", validators=[MinValueValidator(0)])
    used_by_staff = models.PositiveIntegerField("используется сотрудниками", validators=[MinValueValidator(0)])
    ready_to_move = models.PositiveIntegerField("готово к заселению", validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "служебное жилье"
        verbose_name_plural = "Служебное жилье"
        ordering = ("-state_date", "-created_at")

    def __str__(self):
        return f"Жилье: {self.total_count}"

    def clean(self):
        errors = {}
        validate_lte(errors, "used_by_staff", self.used_by_staff, self.total_count, "Используемого жилья не может быть больше общего количества.")
        validate_lte(errors, "ready_to_move", self.ready_to_move, self.total_count, "Готового к заселению жилья не может быть больше общего количества.")
        if self.used_by_staff is not None and self.ready_to_move is not None and self.total_count is not None and self.used_by_staff + self.ready_to_move > self.total_count:
            errors["ready_to_move"] = "Сумма используемого и готового к заселению жилья не может быть больше общего количества."
        if errors:
            raise ValidationError(errors)


class BuildingRepairRequest(TrackableRequest):
    request_number = models.CharField("номер", max_length=80)
    request_date = models.DateField("дата")
    status = models.CharField("исполнение заявки", max_length=20, choices=NeedStatus.choices, default=NeedStatus.IN_WORK, db_index=True)
    completed_at = models.DateField("дата исполнения", null=True, blank=True)

    class Meta:
        verbose_name = "текущий ремонт"
        verbose_name_plural = "Текущий ремонт зданий, помещений, сооружений / Заявка"
        ordering = ("-request_date",)
        indexes = [models.Index(fields=["territorial_organ", "request_date", "status"])]

    def __str__(self):
        return f"Заявка текущего ремонта № {self.request_number}"
