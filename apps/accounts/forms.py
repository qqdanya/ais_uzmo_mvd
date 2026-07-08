from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ActivationAttempt


ACTIVATION_MAX_ATTEMPTS = 5
ACTIVATION_LOCKOUT_SECONDS = 15 * 60


def _recent_failed_attempts(username):
    """Return the failed-attempt count for username within the lockout window.

    Opportunistically prunes expired rows so the table stays bounded without
    needing a separate cleanup job.
    """
    cutoff = timezone.now() - timedelta(seconds=ACTIVATION_LOCKOUT_SECONDS)
    ActivationAttempt.objects.filter(attempted_at__lt=cutoff).delete()
    return ActivationAttempt.objects.filter(username__iexact=username).count()


def _record_failed_attempt(username):
    ActivationAttempt.objects.create(username=username)


def _clear_failed_attempts(username):
    ActivationAttempt.objects.filter(username__iexact=username).delete()


class AccountActivationForm(forms.Form):
    username = forms.CharField(label="Логин", max_length=150)
    activation_code = forms.CharField(label="Код активации", max_length=6, min_length=6)
    password1 = forms.CharField(label="Придумайте пароль", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Повторите пароль", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control auth-ascii-input")
            field.widget.attrs.setdefault("autocapitalize", "none")
            field.widget.attrs.setdefault("spellcheck", "false")
        self.fields["username"].widget.attrs.setdefault("autocomplete", "username")
        self.fields["activation_code"].widget.attrs.setdefault("autocomplete", "one-time-code")
        self.fields["activation_code"].widget.attrs.setdefault("inputmode", "numeric")
        self.fields["activation_code"].widget.attrs.setdefault("pattern", "[0-9]{6}")
        self.fields["password1"].widget.attrs.setdefault("autocomplete", "new-password")
        self.fields["password2"].widget.attrs.setdefault("autocomplete", "new-password")
        self.user = None

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get("username") or "").strip()
        activation_code = (cleaned.get("activation_code") or "").strip().upper()
        password1 = cleaned.get("password1") or ""
        password2 = cleaned.get("password2") or ""

        User = get_user_model()
        self.user = User.objects.filter(username=username, is_active=True).first()
        profile = getattr(self.user, "profile", None) if self.user else None
        if not self.user or not profile:
            raise ValidationError("Учетная запись для активации не найдена.")
        if self.user.has_usable_password():
            raise ValidationError("Учетная запись уже активирована. Используйте обычный вход в систему.")

        if _recent_failed_attempts(username) >= ACTIVATION_MAX_ATTEMPTS:
            raise ValidationError("Слишком много попыток активации. Повторите позже.")

        if not profile.activation_code or profile.activation_code.upper() != activation_code:
            _record_failed_attempt(username)
            raise ValidationError("Неверный код активации.")
        _clear_failed_attempts(username)

        if password1 != password2:
            self.add_error("password2", "Пароли не совпадают.")
        validate_password(password1, self.user)
        cleaned["activation_code"] = activation_code
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.save(update_fields=["password"])
        profile = self.user.profile
        profile.activation_code = ""
        profile.save(update_fields=["activation_code"])
        return self.user
