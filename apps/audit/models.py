from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Создание"
        UPDATE = "update", "Изменение"
        DELETE = "delete", "Удаление"
        LOGIN = "login", "Вход"
        LOGOUT = "logout", "Выход"

    class EventType(models.TextChoices):
        RECORD_CREATED = "record_created", "Создание записи"
        RECORD_UPDATED = "record_updated", "Изменение записи"
        MOVED_TO_TRASH = "moved_to_trash", "Перемещение в корзину"
        RECORD_PURGED = "record_permanently_deleted", "Окончательное удаление записи"
        REQUEST_RESTORED = "request_restored_from_trash", "Восстановление заявки"
        PHOTO_RESTORED = "photo_restored_from_trash", "Восстановление фотографии"
        FOLDER_RESTORED = "photo_folder_tree_restored_from_trash", "Восстановление папки"
        PHOTO_PURGED = "photo_file_permanently_deleted", "Окончательное удаление фотографии"
        FOLDER_PURGED = "photo_folder_tree_permanently_deleted", "Окончательное удаление папки"
        STATUS_CHANGED = "request_status_changed", "Изменение статуса заявки"
        PHOTOS_ATTACHED = "request_photos_attached", "Прикрепление фотографий"
        PHOTOS_DETACHED = "request_photos_detached", "Открепление фотографий"
        TMC_ITEM_ADDED = "tmc_item_added", "Добавление позиции ТМЦ"
        TMC_ITEM_REMOVED = "tmc_item_removed", "Удаление позиции ТМЦ"
        TMC_QUANTITY_CHANGED = "tmc_item_quantity_changed", "Изменение количества ТМЦ"
        TMC_PRODUCT_CREATED = "tmc_product_created", "Добавление наименования ТМЦ"
        EMPLOYEE_CREATED = "employee_created", "Создание сотрудника"
        EMPLOYEE_PERMISSIONS = "employee_permissions_updated", "Изменение прав сотрудника"
        EMPLOYEE_BLOCKED = "employee_blocked", "Блокировка сотрудника"
        EMPLOYEE_UNBLOCKED = "employee_unblocked", "Разблокировка сотрудника"
        EMPLOYEE_ACTIVATION_RESET = "employee_activation_reset", "Сброс активации сотрудника"
        EMPLOYEE_DELETED = "employee_deleted", "Удаление сотрудника"
        ACCOUNT_ACTIVATED = "account_activated", "Активация учётной записи"
        SETTINGS_UPDATED = "settings_updated", "Изменение настроек"
        SETTINGS_RESET = "settings_reset", "Сброс настроек"
        PASSWORD_CHANGED = "password_changed", "Смена пароля"
        TABLE_EXPORTED = "table_exported", "Экспорт таблицы"
        PHOTO_DOWNLOADED = "photo_downloaded", "Скачивание фотографии"
        PHOTO_ARCHIVE_DOWNLOADED = "photo_archive_downloaded", "Скачивание архива фотографий"
        PERSONAL_TRASH_ITEM_REMOVED = "personal_trash_item_removed", "Удаление из личной корзины"
        PERSONAL_TRASH_CLEARED = "personal_trash_cleared", "Очистка личной корзины"
        LOGIN = "login", "Вход в систему"
        LOGOUT = "logout", "Выход из системы"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField("действие", max_length=20, choices=Action.choices, db_index=True)
    event_type = models.CharField("тип события", max_length=64, choices=EventType.choices, blank=True, db_index=True)
    operation_id = models.CharField("операция", max_length=36, blank=True, db_index=True)
    model_name = models.CharField("модель", max_length=120, blank=True, db_index=True)
    object_id = models.CharField("ID объекта", max_length=64, blank=True)
    object_repr = models.CharField("объект", max_length=255, blank=True)
    old_values = models.JSONField("старые значения", null=True, blank=True)
    new_values = models.JSONField("новые значения", null=True, blank=True)
    territorial_organ = models.ForeignKey("directory.TerritorialOrgan", verbose_name="территориальный орган", null=True, blank=True, on_delete=models.SET_NULL)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User-Agent", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "запись аудита"
        verbose_name_plural = "журнал действий"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["action", "model_name", "created_at"]),
            # scope_logs_for_user()/filtered_logs() always narrow by
            # territorial_organ (non-admins) or user (employee detail,
            # activity stats) before ordering by -created_at - neither
            # column's default single-field index covers that combination.
            models.Index(fields=["territorial_organ", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.get_action_display()} {self.object_repr}"

    def save(self, *args, **kwargs):
        if not self.event_type:
            values = self.new_values if isinstance(self.new_values, dict) else {}
            explicit = values.get("audit_event")
            self.event_type = explicit or {
                self.Action.CREATE: self.EventType.RECORD_CREATED,
                self.Action.UPDATE: self.EventType.RECORD_UPDATED,
                self.Action.DELETE: self.EventType.MOVED_TO_TRASH,
                self.Action.LOGIN: self.EventType.LOGIN,
                self.Action.LOGOUT: self.EventType.LOGOUT,
            }.get(self.action, "")
        super().save(*args, **kwargs)
