from django.urls import path

from .views import audit_log

urlpatterns = [path("", audit_log, name="audit_log")]
