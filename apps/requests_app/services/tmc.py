from apps.audit.models import AuditLog
from apps.audit.utils import serialize_instance, write_audit

from ..models import TmcProduct, TmcRequestItem, normalize_product_name


def clean_product_name(value):
    return " ".join((value or "").split())


def product_tokens(value):
    return {token for token in normalize_product_name(value).split() if token}


def levenshtein_distance(left, right):
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def similarity_ratio(left, right):
    left = normalize_product_name(left)
    right = normalize_product_name(right)
    longest = max(len(left), len(right))
    if not longest:
        return 1
    return 1 - (levenshtein_distance(left, right) / longest)


def fuzzy_threshold(value):
    length = len(normalize_product_name(value))
    if length <= 4:
        return .92
    if length <= 7:
        return .82
    return .74


def best_fuzzy_similarity(query_normalized, product):
    candidates = [product.normalized_name]
    product_tokens_sorted = sorted(product_tokens(product.name))
    if len(product_tokens_sorted) > 1:
        candidates.append(" ".join(product_tokens_sorted))
    return max(similarity_ratio(query_normalized, candidate) for candidate in candidates if candidate)


def tmc_product_suggestions(query, limit=8):
    query = clean_product_name(query)
    if not query:
        return []
    query_normalized = normalize_product_name(query)
    query_tokens = product_tokens(query)
    suggestions = []
    for product in TmcProduct.objects.filter(is_active=True):
        product_tokens_set = product_tokens(product.name)
        if not product_tokens_set:
            continue
        if product.normalized_name == query_normalized:
            score = 100
        elif query_tokens and query_tokens.issubset(product_tokens_set):
            score = 90
        elif query_tokens and product_tokens_set.issubset(query_tokens):
            score = 80
        elif query_normalized and query_normalized in product.normalized_name:
            score = 70
        else:
            common_tokens = query_tokens & product_tokens_set
            if common_tokens:
                score = 50 + len(common_tokens)
            else:
                ratio = best_fuzzy_similarity(query_normalized, product)
                score = 40 + int(ratio * 10) if ratio >= fuzzy_threshold(query_normalized) else 0
        if score:
            suggestions.append((score, product.name.casefold(), product))
    suggestions.sort(key=lambda item: (-item[0], item[1]))
    return [product for _, __, product in suggestions[:limit]]


def get_or_create_tmc_product(name, unit, product_id=None):
    name = clean_product_name(name)
    unit = clean_product_name(unit) or "шт."
    if product_id and str(product_id).isdigit():
        product = TmcProduct.objects.filter(pk=product_id, is_active=True).first()
        if product:
            return product, False
    normalized_name = normalize_product_name(name)
    product = TmcProduct.objects.filter(normalized_name=normalized_name).first()
    if product:
        return product, False
    return TmcProduct.objects.create(name=name, unit=unit), True


def tmc_item_rows_from_request(request):
    rows = []
    errors = []
    product_ids = request.POST.getlist("item_product")
    names = request.POST.getlist("item_name")
    quantities = request.POST.getlist("item_quantity")
    units = request.POST.getlist("item_unit")
    for index, name in enumerate(names):
        name = clean_product_name(name)
        quantity_raw = quantities[index].strip() if index < len(quantities) else ""
        unit = clean_product_name(units[index]) if index < len(units) else "шт."
        product_id = product_ids[index].strip() if index < len(product_ids) else ""
        if not name and not quantity_raw:
            continue
        row = {"product_id": product_id, "name": name, "quantity": quantity_raw, "unit": unit or "шт."}
        if not name:
            errors.append("Укажите наименование в каждой заполненной позиции.")
        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                raise ValueError
            row["quantity"] = quantity
        except (TypeError, ValueError):
            errors.append(f"Укажите положительное количество для позиции «{name or 'без наименования'}».")
        rows.append(row)
    if not rows:
        errors.append("Добавьте хотя бы одну позицию заявки.")
        rows.append(tmc_blank_item_row())
    return rows, errors


def tmc_blank_item_row():
    return {"product_id": "", "name": "", "quantity": "", "unit": "шт."}


def tmc_item_rows_from_instance(instance):
    if not instance:
        return [tmc_blank_item_row()]
    return [{"product_id": item.product_id or "", "name": item.name, "quantity": item.quantity, "unit": item.unit} for item in instance.items.all()] or [tmc_blank_item_row()]


def tmc_item_audit_rows(instance):
    if not instance:
        return []
    return [
        {"name": item.name, "quantity": item.quantity, "unit": item.unit}
        for item in instance.items.all()
    ]


def tmc_item_audit_text(rows):
    return "; ".join(f"{row['name']} - {row['quantity']} {row['unit']}" for row in rows)


def tmc_item_change_events(old_rows, new_rows):
    old_map = {(row["name"].casefold(), row["unit"].casefold()): row for row in old_rows}
    new_map = {(row["name"].casefold(), row["unit"].casefold()): row for row in new_rows}
    events = []
    added = [new_map[key] for key in new_map.keys() - old_map.keys()]
    removed = [old_map[key] for key in old_map.keys() - new_map.keys()]
    quantity_changed = [
        {"old": old_map[key], "new": new_map[key]}
        for key in old_map.keys() & new_map.keys()
        if old_map[key]["quantity"] != new_map[key]["quantity"]
    ]
    if added:
        events.append(("tmc_item_added", "", tmc_item_audit_text(added)))
    if removed:
        events.append(("tmc_item_removed", tmc_item_audit_text(removed), ""))
    if quantity_changed:
        events.append((
            "tmc_item_quantity_changed",
            tmc_item_audit_text([item["old"] for item in quantity_changed]),
            tmc_item_audit_text([item["new"] for item in quantity_changed]),
        ))
    return events


def write_tmc_item_audit_events(obj, old_rows, new_rows, request):
    for event, old_value, new_value in tmc_item_change_events(old_rows, new_rows):
        write_audit(
            AuditLog.Action.UPDATE,
            obj,
            old_values={"items": old_value},
            new_values={"audit_event": event, "items": new_value},
            request=request,
        )


def tmc_snapshot(instance):
    data = serialize_instance(instance)
    data["items"] = "; ".join(str(item) for item in instance.items.all())
    return data
