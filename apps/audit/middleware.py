import threading

from django.utils import timezone

_local = threading.local()


def get_current_request():
    return getattr(_local, "request", None)


class RequestAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            if request.user.is_authenticated:
                profile = getattr(request.user, "profile", None)
                now = timezone.now()
                if profile and (not profile.last_seen_at or profile.last_seen_at < now - timezone.timedelta(minutes=1)):
                    profile.last_seen_at = now
                    profile.save(update_fields=["last_seen_at"])
            return self.get_response(request)
        finally:
            _local.request = None
