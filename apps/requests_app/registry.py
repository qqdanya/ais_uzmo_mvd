from . import models


def table(key, title, model, department, fields, form_fields=None, parent_title=None):
    return {
        "key": key,
        "title": title,
        "parent_title": parent_title,
        "model": model,
        "department": department,
        "fields": fields,
        "form_fields": form_fields or fields,
    }


TABLES = {
    "tmc": [
        table("tmc-requests", "Заявка", models.TmcRequest, "tmc", ["request_number", "request_date", "items_summary", "status", "due_date", "comment"]),
    ],
    "transport": [
        table(
            "vehicle-repair",
            "Заявка на ремонт",
            models.VehicleRepairRequest,
            "transport",
            ["request_number", "request_date", "status", "comment"],
            ["request_number", "request_date", "status", "completed_at", "comment"],
        ),
    ],
    "fire": [
        table("fire-extinguishers", "Огнетушители", models.FireExtinguisher, "fire", ["state_date", "required_count", "available_count", "expiry_date", "writeoff_count"]),
        table("fire-alarm", "Пожарная сигнализация", models.FireAlarm, "fire", ["state_date", "required_objects", "equipped_objects", "broken_objects"]),
        table("security-alarm", "Охранная сигнализация", models.SecurityAlarm, "fire", ["state_date", "required_objects", "equipped_objects", "broken_objects"]),
        table(
            "fire-requests",
            "Заявка",
            models.FireDepartmentRequest,
            "fire",
            ["request_number", "request_date", "status", "comment"],
            ["request_number", "request_date", "status", "completed_at", "comment"],
        ),
    ],
    "antiterror": [
        table(
            "anti-terror",
            "Заявка (акт обследования)",
            models.AntiTerrorMeasure,
            "antiterror",
            ["request_number", "request_date", "status", "comment"],
            ["request_number", "request_date", "status", "completed_at", "comment"],
        ),
    ],
    "citsizi": [
        table(
            "citsizi-equipment",
            "Заявка",
            models.CitsiziEquipment,
            "citsizi",
            ["request_number", "request_date", "quantity", "status", "equipment_type", "comment"],
            ["request_number", "request_date", "quantity", "status", "equipment_type", "due_date", "comment"],
        ),
    ],
    "uoto": [
        table("service-housing", "Служебное жилье", models.ServiceHousing, "uoto", ["state_date", "total_count", "used_by_staff", "ready_to_move"]),
        table(
            "building-repair",
            "Заявка",
            models.BuildingRepairRequest,
            "uoto",
            ["request_number", "request_date", "status", "comment"],
            ["request_number", "request_date", "status", "completed_at", "comment"],
            parent_title="Текущий ремонт зданий, помещений, сооружений",
        ),
    ],
}

# Вкладка временно скрыта по требованию заказчика. Конфигурация оставлена,
# чтобы быстро вернуть таблицу без восстановления модели и представлений.
HIDDEN_TABLES = [
    table("vehicle-inventory", "Автотранспорт", models.VehicleInventory, "transport", ["state_date", "required_count", "available_count", "broken_count", "writeoff_count"]),
]

TABLE_BY_KEY = {item["key"]: item for group in TABLES.values() for item in group}
TABLE_BY_KEY.update({item["key"]: item for item in HIDDEN_TABLES})
