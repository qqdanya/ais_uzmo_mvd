from datetime import timedelta

from django.utils import timezone


def recent_failed_attempts(model, username, lockout_seconds):
    """Return the failed-attempt count for username within the lockout window.

    Opportunistically prunes expired rows so the table stays bounded without
    needing a separate cleanup job.
    """
    cutoff = timezone.now() - timedelta(seconds=lockout_seconds)
    model.objects.filter(attempted_at__lt=cutoff).delete()
    return model.objects.filter(username__iexact=username).count()


def record_failed_attempt(model, username):
    model.objects.create(username=username)


def clear_failed_attempts(model, username):
    model.objects.filter(username__iexact=username).delete()
