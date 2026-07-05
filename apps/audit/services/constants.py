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
}
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
    "request_status_changed": "Изменен статус заявки",
    "request_photos_attached": "Прикреплены фотографии к заявке",
    "request_photos_detached": "Откреплены фотографии от заявки",
    "tmc_item_added": "Добавлена позиция ТМЦ",
    "tmc_item_removed": "Удалена позиция ТМЦ",
    "tmc_item_quantity_changed": "Изменено количество ТМЦ",
    "tmc_product_created": "Создан товар в справочнике ТМЦ",
    "employee_created": "Создан сотрудник",
    "employee_permissions_updated": "Обновлены права сотрудника",
    "employee_blocked": "Сотрудник заблокирован",
    "employee_unblocked": "Сотрудник разблокирован",
    "employee_activation_reset": "Сброшена активация сотрудника",
}
