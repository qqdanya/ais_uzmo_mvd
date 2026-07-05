from django.http import QueryDict

from apps.directory.models import Department, TerritorialOrgan

from ..permissions import can_view
from ..registry import TABLES


DEPARTMENT_ICONS = {
    "tmc": "bi-box-seam",
    "transport": "bi-truck",
    "fire": "bi-fire",
    "antiterror": "bi-shield-lock",
    "citsizi": "bi-router",
    "uoto": "bi-building",
}


def active_organs():
    return TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).prefetch_related("children")


def selected_organs_from_request(request, fallback_organ):
    raw_ids = request.GET.getlist("organ_ids")
    if not raw_ids and request.GET.get("organ_ids"):
        raw_ids = request.GET["organ_ids"].split(",")
    ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not ids:
        return [fallback_organ]
    organs = list(
        TerritorialOrgan.objects.filter(pk__in=ids, is_active=True, parent__isnull=True).order_by(
            "order_number",
            "name",
        )
    )
    allowed = [organ for organ in organs if can_view(request.user, organ)]
    return allowed or [fallback_organ]


def selected_organs_querystring(organs):
    query = QueryDict(mutable=True)
    for organ in organs:
        query.appendlist("organ_ids", str(organ.pk))
    return query.urlencode()


def dashboard_context():
    organs = active_organs()
    departments = list(Department.objects.filter(is_active=True))
    for department in departments:
        department.icon_class = DEPARTMENT_ICONS.get(department.slug, "bi-folder2-open")
    return {
        "organs": organs,
        "departments": departments,
        "selected_organ": organs.first(),
        "selected_department": departments[0] if departments else None,
        "tables": TABLES,
    }


def tables_panel_context(request, organ, department):
    selected_organs = selected_organs_from_request(request, organ)
    department_tables = TABLES[department.slug]
    requested_table_key = request.GET.get("table")
    table = next((item for item in department_tables if item["key"] == requested_table_key), department_tables[0])
    table_query = request.GET.copy()
    table_query.pop("table", None)
    return {
        "organ": selected_organs[0],
        "department": department,
        "tables": department_tables,
        "active_table": table,
        "selected_organs": selected_organs,
        "is_multi_organ": len(selected_organs) > 1,
        "organ_querystring": selected_organs_querystring(selected_organs) if len(selected_organs) > 1 else "",
        "table_querystring": table_query.urlencode(),
    }
