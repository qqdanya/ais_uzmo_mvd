from django.urls import path

from .views import audit_detail, audit_log

urlpatterns = [
    path("", audit_log, name="audit_log"),
    path("<int:pk>/", audit_detail, name="audit_detail"),
]
