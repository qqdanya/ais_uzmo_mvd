import json


def htmx_triggers(message, level="success"):
    return json.dumps({"modal:close": True, "toast": {"message": message, "level": level}})


def toast_trigger(message, level="success", **extra):
    payload = {"toast": {"message": message, "level": level}}
    payload.update(extra)
    return json.dumps(payload)
