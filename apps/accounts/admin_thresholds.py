"""Configurable thresholds for the executive dashboard.

The defaults live in code, while runtime overrides are stored in a small JSON
file in the project root. This keeps the feature migration-free and lets the
leader adjust dashboard sensitivity from the control panel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

DEFAULT_REQUEST_STALE_WORKDAYS = 14
DEFAULT_ASSET_STALE_DAYS = 60

THRESHOLD_LIMITS = {
    "request_stale_workdays": {"min": 1, "max": 90},
    "asset_stale_days": {"min": 1, "max": 365},
}

THRESHOLD_LABELS = {
    "request_stale_workdays": "Просроченные заявки, рабочих дней",
    "asset_stale_days": "Устаревшие сведения материальной базы, календарных дней",
}

_THRESHOLDS_CACHE = {"mtime": None, "values": None}


THRESHOLD_HINTS = {
    "request_stale_workdays": "Заявки в работе дольше этого срока считаются просроченными.",
    "asset_stale_days": "Сведения материальной базы старше этого срока помечаются как давно не обновлявшиеся.",
}


def thresholds_path() -> Path:
    custom_path = getattr(settings, "ADMIN_THRESHOLDS_FILE", None)
    if custom_path:
        return Path(custom_path)
    return Path(settings.BASE_DIR) / "dashboard_thresholds.json"


def default_thresholds() -> dict[str, int]:
    return {
        "request_stale_workdays": DEFAULT_REQUEST_STALE_WORKDAYS,
        "asset_stale_days": DEFAULT_ASSET_STALE_DAYS,
    }


def normalize_thresholds(raw: dict[str, Any] | None) -> dict[str, int]:
    values = default_thresholds()
    raw = raw or {}
    for key, default_value in values.items():
        limits = THRESHOLD_LIMITS[key]
        try:
            value = int(raw.get(key, default_value))
        except (TypeError, ValueError):
            value = default_value
        values[key] = min(max(value, limits["min"]), limits["max"])
    return values


def get_dashboard_thresholds() -> dict[str, int]:
    path = thresholds_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _THRESHOLDS_CACHE["mtime"] = None
        _THRESHOLDS_CACHE["values"] = default_thresholds()
        return dict(_THRESHOLDS_CACHE["values"])

    if _THRESHOLDS_CACHE["mtime"] == mtime and _THRESHOLDS_CACHE["values"] is not None:
        return dict(_THRESHOLDS_CACHE["values"])

    try:
        with path.open("r", encoding="utf-8") as fh:
            values = normalize_thresholds(json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError):
        values = default_thresholds()
    _THRESHOLDS_CACHE["mtime"] = mtime
    _THRESHOLDS_CACHE["values"] = values
    return dict(values)


def save_dashboard_thresholds(values: dict[str, Any]) -> dict[str, int]:
    normalized = normalize_thresholds(values)
    path = thresholds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    temp_path.replace(path)
    _THRESHOLDS_CACHE["mtime"] = None
    _THRESHOLDS_CACHE["values"] = normalized
    return normalized


def reset_dashboard_thresholds() -> dict[str, int]:
    path = thresholds_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return get_dashboard_thresholds()
    _THRESHOLDS_CACHE["mtime"] = None
    _THRESHOLDS_CACHE["values"] = default_thresholds()
    return default_thresholds()


def get_request_stale_workdays() -> int:
    return get_dashboard_thresholds()["request_stale_workdays"]


def get_asset_stale_days() -> int:
    return get_dashboard_thresholds()["asset_stale_days"]


class DynamicThreshold:
    """Small int-like wrapper for existing dashboard modules.

    It lets old imports such as ``REQUEST_STALE_WORKDAYS + 1`` keep working,
    while the value itself is read from the JSON settings file at request time.
    """

    def __init__(self, getter):
        self.getter = getter

    def value(self) -> int:
        return int(self.getter())

    def __int__(self):
        return self.value()

    def __index__(self):
        return self.value()

    def __str__(self):
        return str(self.value())

    def __repr__(self):
        return str(self.value())

    def __format__(self, format_spec):
        return format(self.value(), format_spec)

    def __add__(self, other):
        return self.value() + other

    def __radd__(self, other):
        return other + self.value()

    def __sub__(self, other):
        return self.value() - other

    def __rsub__(self, other):
        return other - self.value()

    def __lt__(self, other):
        return self.value() < other

    def __le__(self, other):
        return self.value() <= other

    def __gt__(self, other):
        return self.value() > other

    def __ge__(self, other):
        return self.value() >= other

    def __eq__(self, other):
        try:
            return self.value() == int(other)
        except (TypeError, ValueError):
            return False


REQUEST_STALE_WORKDAYS = DynamicThreshold(get_request_stale_workdays)
ASSET_STALE_DAYS = DynamicThreshold(get_asset_stale_days)
