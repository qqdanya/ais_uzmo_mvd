from django import forms
from django.contrib.auth import get_user_model
from django.urls import reverse

from .admin_common import multiselect_label
from .admin_employee_core import active_departments, profile_for, top_level_organs
from .models import UserProfile


class EmployeeForm(forms.ModelForm):
    middle_name = forms.CharField(label="Отчество", required=False, max_length=150)
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
        if self.instance and self.current_user and self.instance.pk == self.current_user.pk:
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "Нельзя заблокировать собственную учетную запись.")
            if cleaned.get("role") != UserProfile.Role.ADMIN and not self.instance.is_superuser:
                self.add_error("role", "Нельзя снять с себя административные права.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
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
        "department_label": multiselect_label(selected_departments, "Все отделы", {str(department.pk): department.name for department in departments}),
        "organ_label": multiselect_label(selected_organs, "Все территориальные органы", {str(organ.pk): organ.name for organ in organs}),
        "is_create": mode == "create",
        "back_url": reverse("admin_employees_panel"),
        "title": "Новый сотрудник" if mode == "create" else "Редактирование сотрудника",
        "submit_label": "Создать сотрудника" if mode == "create" else "Сохранить изменения",
    }
