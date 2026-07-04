from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.accounts.views import activate_account, admin_panel, admin_request_detail, admin_requests_panel, admin_summary_data, presence_ping

urlpatterns = [
    path("admin/", admin.site.urls),
    path("control/", admin_panel, name="admin_panel"),
    path("control/requests/", admin_requests_panel, name="admin_requests_panel"),
    path("control/requests/<slug:table_key>/<int:pk>/", admin_request_detail, name="admin_request_detail"),
    path("control/summary-data/", admin_summary_data, name="admin_summary_data"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
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
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
