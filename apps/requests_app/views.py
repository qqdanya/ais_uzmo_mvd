from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from apps.directory.models import Department, TerritorialOrgan

from .permissions import can_view
from .registry import get_table_or_404
from .services.photo_responses import (
    folder_picker_response,
    photo_bulk_upload_response,
    photo_delete_response,
    photo_download_response,
    photo_folder_delete_response,
    photo_folder_download_response,
    photo_folder_form_response,
    photo_form_response,
    photo_preview_response,
    photo_thumbnail_response,
    photos_download_all_response,
    photos_response,
)
from .services.record_forms import record_delete_response, record_form_response
from .services.request_photo_panels import (
    request_photo_picker_response,
    request_photos_download_response,
    request_photos_response,
)
from .services.request_response_panels import (
    request_response_delete_response,
    request_response_update_response,
    request_responses_response,
)
from .services.status_panels import status_history_response, status_update_response
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
        # The organ list itself isn't permission-filtered (any authenticated
        # user can see the full tree), so a lost-access click here is
        # expected (e.g. an admin just revoked it) - tell the user plainly
        # instead of a generic error toast over a stuck loading spinner.
        return render(request, "partials/no_organ_access.html", {"organ": organ})
    return render(request, "partials/organ_info.html", {"organ": organ, "update_dashboard_subunits": True})


@login_required
def department_tables(request, organ_id, department_slug):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    department = get_object_or_404(Department, slug=department_slug, is_active=True)
    if not can_view(request.user, organ):
        return render(request, "partials/no_organ_access.html", {"organ": organ})
    return render(request, "partials/tables_panel.html", tables_panel_context(request, organ, department))


@login_required
def table_data(request, organ_id, table_key):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    if not can_view(request.user, organ):
        return render(request, "partials/no_organ_access.html", {"organ": organ})
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
def record_status_update(request, organ_id, table_key, pk):
    table = get_table_or_404(table_key)
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return status_update_response(
        request,
        organ,
        table_key,
        table,
        pk,
        lambda: table_data(request, organ.pk, table_key),
    )


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
@require_http_methods(["GET", "POST"])
def request_responses(request, organ_id, table_key, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_responses_response(request, organ, table_key, pk)


@login_required
@require_http_methods(["GET", "POST"])
def request_response_update(request, organ_id, table_key, pk, response_pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_response_update_response(request, organ, table_key, pk, response_pk)


@login_required
@require_http_methods(["GET", "POST"])
def request_response_delete(request, organ_id, table_key, pk, response_pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return request_response_delete_response(request, organ, table_key, pk, response_pk)


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
    return photos_response(request, organ)


@login_required
def photo_download(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_download_response(request, organ, pk)


@login_required
def photo_preview(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_preview_response(request, organ, pk)


@login_required
def photo_thumbnail(request, organ_id, pk, size):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_thumbnail_response(request, organ, pk, size)


@login_required
def photos_download_all(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photos_download_all_response(request, organ)


@login_required
def photo_folder_download(request, organ_id, pk):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return photo_folder_download_response(request, organ, pk)


@login_required
def folder_picker(request, organ_id):
    organ = get_object_or_404(TerritorialOrgan, pk=organ_id, is_active=True)
    return folder_picker_response(request, organ)


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
