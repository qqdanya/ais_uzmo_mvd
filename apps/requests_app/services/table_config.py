"""Configuration for request/state table views and exports."""

from apps.requests_app.models import (
    AntiTerrorMeasure,
    BuildingRepairRequest,
    CitsiziEquipment,
    FireDepartmentRequest,
    TmcRequest,
    VehicleFuelRequest,
    VehicleRepairRequest,
)


STATUS_HISTORY_TABLES = {
    "tmc-requests",
    "anti-terror",
    "building-repair",
    "citsizi-equipment",
    "vehicle-repair",
    "vehicle-fuel",
    "fire-requests",
}



REQUEST_TABLE_CONFIG = {
    "tmc-requests": {
        "model": TmcRequest,
        "search_fields": ("request_number", "comment", "items__name"),
        "prefetch": ("items",),
        "distinct_search": True,
        "completed_label": "Дата исполнения / отклонения",
    },
    "vehicle-repair": {
        "model": VehicleRepairRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения / отклонения",
    },
    "vehicle-fuel": {
        "model": VehicleFuelRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения / отклонения",
    },
    "fire-requests": {
        "model": FireDepartmentRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения / отклонения",
    },
    "anti-terror": {
        "model": AntiTerrorMeasure,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения / отклонения",
    },
    "citsizi-equipment": {
        "model": CitsiziEquipment,
        "search_fields": ("request_number", "comment"),
        "equipment_type_filter": True,
        "completed_label": "Дата исполнения / отклонения",
    },
    "building-repair": {
        "model": BuildingRepairRequest,
        "search_fields": ("request_number", "comment"),
        "completed_label": "Дата исполнения / отклонения",
    },
}

REQUEST_PHOTO_TABLES = set(REQUEST_TABLE_CONFIG)
SIMPLE_REQUEST_XLSX_CONFIG = {
    "widths": {
        "request_number": 18,
        "request_date": 14,
        "status": 22,
        "comment": 38,
    },
    "center_columns": {"request_number", "request_date", "status"},
}


XLSX_EXPORT_CONFIG = {
    "vehicle-inventory": {
        "widths": {
            "state_date": 14,
            "required_count": 14,
            "available_count": 14,
            "broken_count": 16,
            "writeoff_count": 38,
        },
        "center_columns": {"state_date", "required_count", "available_count", "broken_count", "writeoff_count"},
    },
    "vehicle-repair": {
        **SIMPLE_REQUEST_XLSX_CONFIG,
    },
    "vehicle-fuel": {
        **SIMPLE_REQUEST_XLSX_CONFIG,
    },
    "fire-extinguishers": {
        "widths": {
            "state_date": 14,
            "required_count": 14,
            "available_count": 14,
            "expiry_date": 24,
            "writeoff_count": 18,
        },
        "center_columns": {"state_date", "required_count", "available_count", "expiry_date", "writeoff_count"},
    },
    "fire-alarm": {
        "widths": {
            "state_date": 14,
            "required_objects": 28,
            "equipped_objects": 26,
            "broken_objects": 28,
        },
        "center_columns": {"state_date", "required_objects", "equipped_objects", "broken_objects"},
    },
    "security-alarm": {
        "widths": {
            "state_date": 14,
            "required_objects": 28,
            "equipped_objects": 26,
            "broken_objects": 28,
        },
        "center_columns": {"state_date", "required_objects", "equipped_objects", "broken_objects"},
    },
    "fire-requests": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
    "anti-terror": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
    "citsizi-equipment": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "quantity": 14,
            "status": 22,
            "equipment_type": 28,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "quantity", "status", "equipment_type"},
    },
    "service-housing": {
        "widths": {
            "state_date": 14,
            "total_count": 18,
            "used_by_staff": 24,
            "ready_to_move": 20,
        },
        "center_columns": {"state_date", "total_count", "used_by_staff", "ready_to_move"},
    },
    "building-repair": {
        "widths": {
            "request_number": 18,
            "request_date": 14,
            "status": 22,
            "comment": 38,
        },
        "center_columns": {"request_number", "request_date", "status"},
    },
}
