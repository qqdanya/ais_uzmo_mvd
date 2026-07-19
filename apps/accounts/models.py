import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_activation_code():
    return "".join(str(secrets.randbelow(10)) for _ in range(6))


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        OPERATOR = "operator", "Оператор"
        OBSERVER = "observer", "Наблюдатель"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OBSERVER)
    allowed_organs = models.ManyToManyField("directory.TerritorialOrgan", blank=True, related_name="allowed_profiles")
    allowed_departments = models.ManyToManyField("directory.Department", blank=True, related_name="allowed_profiles")
    writable_organs = models.ManyToManyField("directory.TerritorialOrgan", blank=True, related_name="writable_profiles")
    writable_departments = models.ManyToManyField("directory.Department", blank=True, related_name="writable_profiles")
    middle_name = models.CharField("отчество", max_length=150, blank=True)
    activation_code = models.CharField("код активации", max_length=32, blank=True)
    last_seen_at = models.DateTimeField("последняя активность", null=True, blank=True)

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"

    @property
    def display_name(self):
        last_name = (self.user.last_name or "").strip()
        first_name = (self.user.first_name or "").strip()
        middle_name = (self.middle_name or "").strip()
        if last_name and first_name:
            initials = f"{first_name[:1]}."
            if middle_name:
                initials = f"{initials}{middle_name[:1]}."
            return f"{last_name} {initials}"
        full_name = self.user.get_full_name().strip()
        return full_name or self.user.username

    @property
    def full_display_name(self):
        parts = [
            (self.user.last_name or "").strip(),
            (self.user.first_name or "").strip(),
            (self.middle_name or "").strip(),
        ]
        full_name = " ".join(part for part in parts if part)
        return full_name or self.display_name

    @property
    def is_online(self):
        if not self.last_seen_at:
            return False
        return self.last_seen_at >= timezone.now() - timedelta(minutes=1)

    @property
    def needs_activation(self):
        return not self.user.has_usable_password()

    def ensure_activation_code(self):
        if not self.activation_code:
            self.activation_code = generate_activation_code()
        return self.activation_code

    def save(self, *args, **kwargs):
        if self.user_id and self.needs_activation:
            self.ensure_activation_code()
        super().save(*args, **kwargs)


class FailedAttempt(models.Model):
    """Shared shape for brute-force lockout counters (login, activation, ...).

    Stored in the DB rather than the cache framework so a lockout is shared
    across all gunicorn worker processes instead of counting independently
    per worker.
    """

    username = models.CharField(max_length=150, db_index=True)
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        abstract = True


class ActivationAttempt(FailedAttempt):
    class Meta(FailedAttempt.Meta):
        verbose_name = "Попытка активации"
        verbose_name_plural = "Попытки активации"


class LoginAttempt(FailedAttempt):
    class Meta(FailedAttempt.Meta):
        verbose_name = "Попытка входа"
        verbose_name_plural = "Попытки входа"


class TrashDismissal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trash_dismissals")
    kind = models.CharField(max_length=16)
    table_key = models.CharField(max_length=64, blank=True)
    object_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "kind", "table_key", "object_id"), name="unique_user_trash_dismissal"),
        ]
