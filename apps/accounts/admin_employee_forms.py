import re

from django import forms
from django.contrib.auth import get_user_model
from django.urls import reverse

from .admin_common import multiselect_label
from .admin_employee_core import active_departments, profile_for, top_level_organs
from .models import UserProfile


TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate_name(value):
    text = (value or "").strip().lower()
    chars = [TRANSLIT_MAP.get(char, char) for char in text]
    slug = re.sub(r"[^a-z0-9]+", "_", "".join(chars)).strip("_")
    return slug or ""


def unique_employee_username(last_name, first_name="", middle_name="", *, instance=None):
    User = get_user_model()
    parts = [transliterate_name(last_name), transliterate_name(first_name), transliterate_name(middle_name)]
    candidates = []
    if parts[0]:
        candidates.append(parts[0])
    if parts[0] and parts[1]:
        candidates.append(f"{parts[0]}_{parts[1]}")
    if parts[0] and parts[1] and parts[2]:
        candidates.append(f"{parts[0]}_{parts[1]}_{parts[2]}")
    if not candidates:
        return ""

    qs = User.objects.all()
    if instance and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    for candidate in candidates:
        if not qs.filter(username=candidate).exists():
            return candidate

    base = candidates[-1]
    suffix = 2
    while qs.filter(username=f"{base}_{suffix}").exists():
        suffix += 1
    return f"{base}_{suffix}"


def existing_employee_usernames(*, instance=None):
    qs = get_user_model().objects.all()
    if instance and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    return sorted({(username or "").strip().lower() for username in qs.values_list("username", flat=True) if username})


class EmployeeForm(forms.ModelForm):
    middle_name = forms.CharField(label="Отчество", required=False, max_length=150)
    username_auto = forms.BooleanField(required=False, initial=True, widget=forms.HiddenInput)
    role = forms.ChoiceField(label="Роль в системе", choices=UserProfile.Role.choices, initial=UserProfile.Role.OPERATOR)
    allowed_departments = forms.ModelMultipleChoiceField(label="Доступные отделы", queryset=active_departments(), required=False)
    allowed_organs = forms.ModelMultipleChoiceField(label="Доступные территориальные органы", queryset=top_level_organs(), required=False)

    class Meta:
        model = get_user_model()
        fields = (
            "last_name",
            "first_name",
            "middle_name",
            "username",
            "role",
            "allowed_departments",
            "allowed_organs",
            "is_active",
        )
        labels = {
            "last_name": "Фамилия",
            "first_name": "Имя",
            "username": "Логин",
            "is_active": "Аккаунт активен, вход разрешён",
        }
        help_texts = {"username": "Логин выдаётся сотруднику вместе с кодом активации."}

    def __init__(self, *args, current_user=None, **kwargs):
        self.current_user = current_user
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = False
        self.fields["first_name"].required = False
        self.fields["username"].required = False
        self.fields["username"].widget.attrs.setdefault("autocomplete", "off")
        self.fields["username"].widget.attrs.setdefault("data-employee-username", "true")
        self.fields["last_name"].widget.attrs.setdefault("data-employee-last-name", "true")
        self.fields["first_name"].widget.attrs.setdefault("data-employee-first-name", "true")
        self.fields["middle_name"].widget.attrs.setdefault("data-employee-middle-name", "true")
        self.fields["allowed_departments"].queryset = active_departments()
        self.fields["allowed_organs"].queryset = top_level_organs()
        if not self.instance.pk and not self.is_bound:
            self.fields["allowed_departments"].initial = []
            self.fields["allowed_organs"].initial = list(self.fields["allowed_organs"].queryset)
        for name, field in self.fields.items():
            if name in {"allowed_departments", "allowed_organs", "role"}:
                continue
            if name in {"is_active"}:
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control form-control-sm admin-control")
        profile = profile_for(self.instance) if self.instance and self.instance.pk else None
        if profile and not self.is_bound:
            self.fields["middle_name"].initial = profile.middle_name
            self.fields["role"].initial = profile.role
            self.fields["allowed_departments"].initial = profile.allowed_departments.all()
            self.fields["allowed_organs"].initial = profile.allowed_organs.all()

    def clean(self):
        cleaned = super().clean()
        last_name = (cleaned.get("last_name") or "").strip()
        first_name = (cleaned.get("first_name") or "").strip()
        middle_name = (cleaned.get("middle_name") or "").strip()
        if not last_name:
            self.add_error("last_name", "Укажите фамилию сотрудника.")
        if not first_name:
            self.add_error("first_name", "Укажите имя сотрудника.")
        if last_name:
            cleaned["last_name"] = last_name
        if first_name:
            cleaned["first_name"] = first_name
        cleaned["middle_name"] = middle_name
        username = (cleaned.get("username") or "").strip().lower()
        auto_username = bool(cleaned.get("username_auto")) or not username
        if auto_username and last_name and first_name:
            username = unique_employee_username(last_name, first_name, middle_name, instance=self.instance)
        cleaned["username"] = username
        if not username and last_name and first_name:
            self.add_error("username", "Не удалось автоматически сформировать логин.")
        if username:
            qs = get_user_model().objects.filter(username=username)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("username", "Пользователь с таким логином уже существует.")
        if self.instance and self.current_user and self.instance.pk == self.current_user.pk:
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "Нельзя заблокировать собственную учетную запись.")
            if cleaned.get("role") != UserProfile.Role.ADMIN and not self.instance.is_superuser:
                self.add_error("role", "Нельзя снять с себя административные права.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data.get("username") or user.username
        is_new = not user.pk
        if is_new:
            user.set_unusable_password()
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.middle_name = self.cleaned_data.get("middle_name", "")
            profile.role = self.cleaned_data.get("role") or UserProfile.Role.OBSERVER
            if is_new or profile.needs_activation:
                profile.ensure_activation_code()
            profile.save()
            profile.allowed_departments.set(self.cleaned_data.get("allowed_departments") or [])
            profile.allowed_organs.set(self.cleaned_data.get("allowed_organs") or [])
        return user


def form_selected_values(form, field_name):
    value = form[field_name].value()
    if value is None:
        return []
    if hasattr(value, "values_list"):
        return [str(item) for item in value.values_list("pk", flat=True)]
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if hasattr(item, "pk"):
                result.append(str(item.pk))
            else:
                result.append(str(item))
        return result
    return [str(value)]


def employee_form_context(request, *, user=None, form=None, mode="create"):
    if form is None:
        form = EmployeeForm(instance=user, current_user=request.user)
    departments = list(active_departments())
    organs = list(top_level_organs())
    selected_departments = form_selected_values(form, "allowed_departments")
    selected_organs = form_selected_values(form, "allowed_organs")
    if mode == "create" and not form.is_bound and not selected_organs:
        selected_organs = [str(organ.pk) for organ in organs]
    role_value_current = (form["role"].value() or UserProfile.Role.OPERATOR)
    role_options = [(str(value), label) for value, label in UserProfile.Role.choices]
    return {
        "active_tab": "employees",
        "mode": mode,
        "form": form,
        "employee": user,
        "profile": profile_for(user) if user else None,
        "departments": departments,
        "organs": organs,
        "selected_departments": selected_departments,
        "selected_organs": selected_organs,
        "selected_role": str(role_value_current),
        "role_options": role_options,
        "role_label": dict(role_options).get(str(role_value_current), "Роль в системе"),
        "existing_usernames": existing_employee_usernames(instance=user),
        "department_label": multiselect_label(selected_departments, "Отделы не выбраны", {str(department.pk): department.name for department in departments}),
        "organ_label": multiselect_label(selected_organs, "Территориальные органы не выбраны", {str(organ.pk): organ.name for organ in organs}),
        "is_create": mode == "create",
        "back_url": reverse("admin_employees_panel"),
        "title": "Новый сотрудник" if mode == "create" else "Редактирование сотрудника",
        "submit_label": "Добавить сотрудника" if mode == "create" else "Сохранить изменения",
    }
