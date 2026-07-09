import threading

from django.utils import timezone

from apps.requests_app.dev_state import is_dev_seed_running

_local = threading.local()


def get_current_request():
    return getattr(_local, "request", None)


class RequestAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            # Skip during a dev seed-data generation for the same reason as
            # presence_ping - this write has no value while that's running
            # and only competes with it for SQLite's write lock.
            if request.user.is_authenticated and not is_dev_seed_running():
                profile = getattr(request.user, "profile", None)
                now = timezone.now()
                if profile and (not profile.last_seen_at or profile.last_seen_at < now - timezone.timedelta(minutes=1)):
                    profile.last_seen_at = now
                    profile.save(update_fields=["last_seen_at"])
            return self.get_response(request)
        finally:
            _local.request = None
