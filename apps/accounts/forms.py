from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .lockout import clear_failed_attempts, record_failed_attempt, recent_failed_attempts
from .models import ActivationAttempt, LoginAttempt


ACTIVATION_MAX_ATTEMPTS = 5
ACTIVATION_LOCKOUT_SECONDS = 15 * 60

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


class DistinctPasswordChangeForm(PasswordChangeForm):
    """Reject a password-change request that would keep the current password."""

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password1")
        if new_password and self.user.check_password(new_password):
            self.add_error(
                "new_password1",
                ValidationError(
                    "должен отличаться от текущего.",
                    code="password_unchanged",
                ),
            )
        return cleaned_data


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
            raise ValidationError("Учётная запись для активации не найдена.")
        if self.user.has_usable_password():
            raise ValidationError("Учётная запись уже активирована. Используйте обычный вход в систему.")

        if recent_failed_attempts(ActivationAttempt, username, ACTIVATION_LOCKOUT_SECONDS) >= ACTIVATION_MAX_ATTEMPTS:
            raise ValidationError("Слишком много попыток активации. Повторите позже.")

        if not profile.activation_code or profile.activation_code.upper() != activation_code:
            record_failed_attempt(ActivationAttempt, username)
            raise ValidationError("Неверный код активации.")
        clear_failed_attempts(ActivationAttempt, username)

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


class RateLimitedAuthenticationForm(AuthenticationForm):
    """Standard Django login form with a DB-backed lockout on repeated failures."""

    def clean(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if username and recent_failed_attempts(LoginAttempt, username, LOGIN_LOCKOUT_SECONDS) >= LOGIN_MAX_ATTEMPTS:
            raise ValidationError("Слишком много попыток входа. Повторите позже.", code="too_many_attempts")

        try:
            cleaned = super().clean()
        except ValidationError:
            if username:
                record_failed_attempt(LoginAttempt, username)
            raise

        if username:
            clear_failed_attempts(LoginAttempt, username)
        return cleaned
