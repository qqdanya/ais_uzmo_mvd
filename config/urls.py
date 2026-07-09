from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.accounts.forms import RateLimitedAuthenticationForm
from apps.accounts.views import activate_account, admin_asset_category_detail, admin_asset_organ_detail, admin_asset_organ_summary, admin_assets_panel, admin_department_detail, admin_departments_panel, admin_employee_action, admin_employee_create, admin_employee_detail, admin_employee_edit, admin_employees_panel, admin_employees_presence_data, admin_organ_detail, admin_organs_panel, admin_panel, admin_request_detail, admin_requests_panel, admin_summary_data, admin_threshold_settings, admin_trash_panel, admin_trash_purge_folder, admin_trash_purge_photo, admin_trash_restore_folder, admin_trash_restore_photo, admin_trash_restore_request, presence_ping

urlpatterns = [
    path("admin/", admin.site.urls),
    path("control/", admin_panel, name="admin_panel"),
    path("control/requests/", admin_requests_panel, name="admin_requests_panel"),
    path("control/requests/<slug:table_key>/<int:pk>/", admin_request_detail, name="admin_request_detail"),
    path("control/organs/", admin_organs_panel, name="admin_organs_panel"),
    path("control/organs/<int:pk>/", admin_organ_detail, name="admin_organ_detail"),
    path("control/departments/", admin_departments_panel, name="admin_departments_panel"),
    path("control/departments/<slug:department_slug>/", admin_department_detail, name="admin_department_detail"),
    path("control/assets/", admin_assets_panel, name="admin_assets_panel"),
    path("control/assets/organs/<int:organ_id>/", admin_asset_organ_summary, name="admin_asset_organ_summary"),
    path("control/assets/<slug:category_key>/", admin_asset_category_detail, name="admin_asset_category_detail"),
    path("control/assets/<slug:category_key>/organs/<int:organ_id>/", admin_asset_organ_detail, name="admin_asset_organ_detail"),
    path("control/employees/", admin_employees_panel, name="admin_employees_panel"),
    path("control/employees/create/", admin_employee_create, name="admin_employee_create"),
    path("control/employees/presence-data/", admin_employees_presence_data, name="admin_employees_presence_data"),
    path("control/employees/<int:pk>/", admin_employee_detail, name="admin_employee_detail"),
    path("control/employees/<int:pk>/edit/", admin_employee_edit, name="admin_employee_edit"),
    path("control/employees/<int:pk>/action/", admin_employee_action, name="admin_employee_action"),
    path("control/summary-data/", admin_summary_data, name="admin_summary_data"),
    path("control/settings/", admin_threshold_settings, name="admin_threshold_settings"),
    path("control/trash/", admin_trash_panel, name="admin_trash_panel"),
    path("control/trash/requests/<slug:table_key>/<int:pk>/restore/", admin_trash_restore_request, name="admin_trash_restore_request"),
    path("control/trash/photos/<int:pk>/restore/", admin_trash_restore_photo, name="admin_trash_restore_photo"),
    path("control/trash/photos/<int:pk>/purge/", admin_trash_purge_photo, name="admin_trash_purge_photo"),
    path("control/trash/folders/<int:pk>/restore/", admin_trash_restore_folder, name="admin_trash_restore_folder"),
    path("control/trash/folders/<int:pk>/purge/", admin_trash_purge_folder, name="admin_trash_purge_folder"),
    path("accounts/login/", auth_views.LoginView.as_view(authentication_form=RateLimitedAuthenticationForm), name="login"),
    path("accounts/activate/", activate_account, name="account_activate"),
    path("accounts/presence/", presence_ping, name="presence_ping"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password-change/",
        auth_views.PasswordChangeView.as_view(template_name="registration/password_change_form.html"),
        name="password_change",
    ),
    path(
        "accounts/password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"),
        name="password_change_done",
    ),
    path("", include("apps.requests_app.urls")),
    path("audit/", include("apps.audit.urls")),
]

if settings.DEBUG:
    from apps.requests_app.dev_views import dev_seed_data

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [path("dev/seed/", dev_seed_data, name="dev_seed_data")]
