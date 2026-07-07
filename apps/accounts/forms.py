from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError


ACTIVATION_MAX_ATTEMPTS = 5
ACTIVATION_LOCKOUT_SECONDS = 15 * 60


def _activation_attempts_key(username):
    return f"activation_attempts:{username.lower()}"


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

        attempts_key = _activation_attempts_key(username)
        if cache.get(attempts_key, 0) >= ACTIVATION_MAX_ATTEMPTS:
            raise ValidationError("Слишком много попыток активации. Повторите позже.")

        if not profile.activation_code or profile.activation_code.upper() != activation_code:
            cache.set(attempts_key, cache.get(attempts_key, 0) + 1, ACTIVATION_LOCKOUT_SECONDS)
            raise ValidationError("Неверный код активации.")
        cache.delete(attempts_key)

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
