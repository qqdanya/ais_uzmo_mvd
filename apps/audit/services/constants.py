from apps.requests_app.registry import TABLE_BY_KEY

from apps.audit.models import AuditLog


SYSTEM_FIELD_NAMES = {
    "id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "is_deleted",
    "audit_event",
    "scope",
    "kind",
    "format",
    "table_key",
    "table_title",
    "department_slug",
    "organ_ids",
    "organ_names",
    "organ_count",
    "group_mode",
    "filter_conditions",
    "photo_count",
    "object_count",
    "restored_folder_ids",
    "folder_ids",
    "file_name",
    "file_size",
    "deleted_file_names",
    "deleted_file_names_truncated",
    "request_photo_link_count",
    "photo_items",
    "normalized_name",
}

# Employee and control-panel administration is intentionally visible only in
# the full administrator journal.  Keep this list in one place so that the
# queryset scope and the event-type filter cannot drift apart.
ADMIN_ONLY_EVENT_TYPES = {
    AuditLog.EventType.EMPLOYEE_CREATED,
    AuditLog.EventType.EMPLOYEE_PERMISSIONS,
    AuditLog.EventType.EMPLOYEE_BLOCKED,
    AuditLog.EventType.EMPLOYEE_UNBLOCKED,
    AuditLog.EventType.EMPLOYEE_ACTIVATION_RESET,
    AuditLog.EventType.EMPLOYEE_DELETED,
    AuditLog.EventType.ACCOUNT_ACTIVATED,
    AuditLog.EventType.PASSWORD_CHANGED,
    AuditLog.EventType.SETTINGS_UPDATED,
    AuditLog.EventType.SETTINGS_RESET,
}
ADMIN_ONLY_MODEL_NAMES = {"User"}
MODEL_HIDDEN_FIELD_NAMES = {
    "TerritorialOrganPhoto": {"created_department"},
    "TerritorialOrganPhotoFolder": {"created_department"},
}
ACTION_DISPLAY_LABELS = {
    AuditLog.Action.CREATE: "Создание",
    AuditLog.Action.UPDATE: "Редактирование",
    AuditLog.Action.DELETE: "Удаление",
    AuditLog.Action.LOGIN: "Вход",
    AuditLog.Action.LOGOUT: "Выход",
}
ACTION_BADGES = {
    AuditLog.Action.CREATE: "audit-action-create",
    AuditLog.Action.UPDATE: "audit-action-update",
    AuditLog.Action.DELETE: "audit-action-delete",
    AuditLog.Action.LOGIN: "audit-action-login",
    AuditLog.Action.LOGOUT: "audit-action-logout",
}
EVENT_BADGES = {
    AuditLog.EventType.RECORD_CREATED: "audit-event-create",
    AuditLog.EventType.RECORD_UPDATED: "audit-event-update",
    AuditLog.EventType.MOVED_TO_TRASH: "audit-event-trash",
    AuditLog.EventType.RECORD_PURGED: "audit-event-purge",
    AuditLog.EventType.REQUEST_RESTORED: "audit-event-restore",
    AuditLog.EventType.PHOTO_RESTORED: "audit-event-restore",
    AuditLog.EventType.FOLDER_RESTORED: "audit-event-restore",
    AuditLog.EventType.PHOTO_PURGED: "audit-event-purge",
    AuditLog.EventType.FOLDER_PURGED: "audit-event-purge",
    AuditLog.EventType.STATUS_CHANGED: "audit-event-status",
    AuditLog.EventType.PHOTOS_ATTACHED: "audit-event-photo",
    AuditLog.EventType.PHOTOS_DETACHED: "audit-event-photo",
    AuditLog.EventType.EMPLOYEE_PERMISSIONS: "audit-event-access",
    AuditLog.EventType.EMPLOYEE_BLOCKED: "audit-event-access",
    AuditLog.EventType.EMPLOYEE_UNBLOCKED: "audit-event-access",
    AuditLog.EventType.EMPLOYEE_ACTIVATION_RESET: "audit-event-access",
    AuditLog.EventType.SETTINGS_UPDATED: "audit-event-access",
    AuditLog.EventType.SETTINGS_RESET: "audit-event-access",
    AuditLog.EventType.PASSWORD_CHANGED: "audit-event-access",
    AuditLog.EventType.TABLE_EXPORTED: "audit-event-export",
    AuditLog.EventType.PHOTO_DOWNLOADED: "audit-event-export",
    AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED: "audit-event-export",
    AuditLog.EventType.LOGIN: "audit-event-login",
    AuditLog.EventType.LOGOUT: "audit-event-logout",
}
MODEL_TABLES = {config["model"].__name__: config for config in TABLE_BY_KEY.values()}
PHOTO_OBJECT_MODELS = {"TerritorialOrganPhoto"}
FOLDER_OBJECT_MODELS = {"TerritorialOrganPhotoFolder"}
TABLE_OBJECT_MODELS = set(MODEL_TABLES)
OBJECT_FILTERS = (
    ("table_record", "Запись в таблице", TABLE_OBJECT_MODELS),
    ("photo", "Фотография", PHOTO_OBJECT_MODELS),
    ("folder", "Папка", FOLDER_OBJECT_MODELS),
)
OBJECT_MODEL_NAMES = {key: set(models) for key, _, models in OBJECT_FILTERS}
AUDIT_EVENT_SUMMARIES = {
    "record_permanently_deleted": "Запись удалена без возможности восстановления",
    "request_status_changed": "Изменён статус заявки",
    "request_photos_attached": "Прикреплены фотографии к заявке",
    "request_photos_detached": "Откреплены фотографии от заявки",
    "photo_restored_from_trash": "Фотография восстановлена",
    "request_restored_from_trash": "Заявка восстановлена из корзины",
    "photo_folder_tree_restored_from_trash": "Папка и её содержимое восстановлены",
    "photo_file_permanently_deleted": "Фотография удалена без возможности восстановления",
    "photo_folder_tree_permanently_deleted": "Папка и её содержимое удалены без возможности восстановления",
    "tmc_item_added": "Добавлена позиция ТМЦ",
    "tmc_item_removed": "Удалена позиция ТМЦ",
    "tmc_item_quantity_changed": "Изменено количество ТМЦ",
    "tmc_product_created": "Создан товар в справочнике ТМЦ",
    "employee_created": "Создан сотрудник",
    "employee_permissions_updated": "Обновлены права сотрудника",
    "employee_blocked": "Сотрудник заблокирован",
    "employee_unblocked": "Сотрудник разблокирован",
    "employee_activation_reset": "Сброшена активация сотрудника",
    "employee_deleted": "Сотрудник удалён",
    "account_activated": "Учётная запись активирована",
    "settings_updated": "Изменены настройки контроля",
    "settings_reset": "Настройки контроля сброшены",
    "password_changed": "Пользователь изменил пароль",
    "table_exported": "Таблица экспортирована",
    "photo_downloaded": "Скачана фотография",
    "photo_archive_downloaded": "Скачан архив фотографий",
    "personal_trash_item_removed": "Объект убран из личной корзины",
    "personal_trash_cleared": "Личная корзина очищена",
}
