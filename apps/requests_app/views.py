from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from apps.directory.models import Department, TerritorialOrgan

from .permissions import can_view
from .registry import get_table_or_404
from .services.photo_responses import (
    photo_bulk_upload_response,
    photo_delete_response,
    photo_download_response,
    photo_folder_delete_response,
    photo_folder_download_response,
    photo_folder_form_response,
    photo_form_response,
    photos_download_all_response,
    render_photos,
)
from .services.record_forms import record_delete_response, record_form_response
from .services.request_photo_panels import (
    request_photo_picker_response,
    request_photos_download_response,
    request_photos_response,
)
from .services.status_panels import status_history_response
from .services.table_context import build_table_data_context
from .services.table_exports import export_table_response
from .services.tmc import tmc_product_suggestions
from .services.ui_context import (
    dashboard_context,
    selected_organs_from_request,
    selected_organs_querystring,
    tables_panel_context,
)


@login_required
def dashboard(request):
    return render(request, "dashboard/index.html", dashboard_context())


@login_required
def organ_info(request, pk):
    organ = get_object_or_404(TerritorialOrgan.objects.prefetch_related("children"), pk=pk, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    return render(request, "partials/organ_info.html", {"organ": organ})


@login_required
def department_tables(request, organ_id, department_slug):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    department = get_object_or_404(Department, slug=department_slug, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    return render(request, "partials/tables_panel.html", tables_panel_context(request, organ, department))


@login_required
def table_data(request, organ_id, table_key):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    selected_organs = selected_organs_from_request(request, organ)
    return render(
        request,
        "partials/table_data.html",
        build_table_data_context(
            request,
            organ,
            table,
            table_key,
            selected_organs,
            selected_organs_querystring(selected_organs) if len(selected_organs) > 1 else "",
        ),
    )


@login_required
def tmc_product_suggest(request):
    suggestions = tmc_product_suggestions(request.GET.get("q", ""))
    return JsonResponse(
        {
            "results": [
                {"id": product.pk, "name": product.name, "unit": product.unit}
                for product in suggestions
            ]
        }
    )


@login_required
def status_history(request, organ_id, table_key, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return status_history_response(request, organ, table_key, pk)


@login_required
@require_http_methods(["GET", "POST"])
def request_photos(request, organ_id, table_key, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_photos_response(request, organ, table_key, pk)


@login_required
def request_photos_download(request, organ_id, table_key, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_photos_download_response(request, organ, table_key, pk)


@login_required
def request_photo_picker(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_photo_picker_response(request, organ)


@login_required
@require_http_methods(["GET", "POST"])
def record_form(request, organ_id, table_key, pk=None):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    instance = get_object_or_404(table["model"], pk=pk, territorial_organ=organ) if pk else None
    return record_form_response(request, organ, table_key, table, instance, lambda: table_data(request, organ.pk, table_key))


@login_required
@require_http_methods(["GET", "POST"])
def record_delete(request, organ_id, table_key, pk):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return record_delete_response(request, organ, table_key, table, pk, lambda: table_data(request, organ.pk, table_key))


@login_required
def export_table(request, organ_id, table_key, fmt):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id)
    if not can_view(request.user, organ):
        raise Http404
    selected_organs = selected_organs_from_request(request, organ)
    return export_table_response(request, organ, table, table_key, fmt, selected_organs)


@login_required
def photos(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        raise Http404
    return render_photos(request, organ)


@login_required
def photo_download(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_download_response(request, organ, pk)


@login_required
def photos_download_all(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photos_download_all_response(request, organ)


@login_required
def photo_folder_download(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_folder_download_response(request, organ, pk)


@login_required
@require_http_methods(["GET", "POST"])
def photo_form(request, organ_id, pk=None):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_form_response(request, organ, pk)


@login_required
@require_http_methods(["GET", "POST"])
def photo_folder_form(request, organ_id, pk=None):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_folder_form_response(request, organ, pk)


@login_required
@require_http_methods(["GET", "POST"])
def photo_folder_delete(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_folder_delete_response(request, organ, pk)


@login_required
@require_http_methods(["GET", "POST"])
def photo_bulk_upload(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_bulk_upload_response(request, organ)


@login_required
@require_http_methods(["GET", "POST"])
def photo_delete(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_delete_response(request, organ, pk)
