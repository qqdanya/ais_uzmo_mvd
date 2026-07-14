from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm

from .models import UserProfile


User = get_user_model()

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class EmployeeCreationForm(forms.ModelForm):
    middle_name = forms.CharField(label="Отчество", required=False, max_length=150)
    role = forms.ChoiceField(label="Роль", choices=UserProfile.Role.choices, initial=UserProfile.Role.OPERATOR)
    allowed_organs = forms.ModelMultipleChoiceField(
        label="Территориальные органы",
        queryset=UserProfile._meta.get_field("allowed_organs").remote_field.model.objects.filter(is_active=True),
        required=False,
    )
    allowed_departments = forms.ModelMultipleChoiceField(
        label="Отделы",
        queryset=UserProfile._meta.get_field("allowed_departments").remote_field.model.objects.filter(is_active=True),
        required=False,
    )

    class Meta:
        model = User
        fields = ("last_name", "first_name", "middle_name", "username", "role", "allowed_organs", "allowed_departments", "is_active", "is_staff", "is_superuser")
        labels = {
            "last_name": "Фамилия",
            "first_name": "Имя",
            "username": "Логин",
            "is_active": "Активен",
            "is_staff": "Доступ к панели администратора",
            "is_superuser": "Полные права администратора",
        }
        help_texts = {"username": "Логин выдается сотруднику для первого входа в систему."}

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    filter_horizontal = ("allowed_organs", "allowed_departments")
    readonly_fields = ("activation_code", "last_seen_at", "needs_activation", "is_online")
    fields = ("role", "middle_name", "allowed_organs", "allowed_departments", "activation_code", "needs_activation", "is_online", "last_seen_at")
    verbose_name = "Профиль сотрудника"
    verbose_name_plural = "Профиль сотрудника"


@admin.register(User)
class EmployeeAdmin(DjangoUserAdmin):
    form = UserChangeForm
    add_form = EmployeeCreationForm
    inlines = (UserProfileInline,)
    list_display = ("employee_name", "username", "employee_role", "activation_state", "online_state", "is_active")
    list_filter = ("is_active", "profile__role", "is_staff", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "profile__middle_name")
    ordering = ("last_name", "first_name", "username")
    add_fieldsets = (
        (
            "Сотрудник",
            {
                "classes": ("wide",),
                "fields": ("last_name", "first_name", "middle_name", "username", "role", "allowed_organs", "allowed_departments", "is_active", "is_staff", "is_superuser"),
            },
        ),
    )
    fieldsets = (
        ("Учётная запись", {"fields": ("username", "password")}),
        ("Сотрудник", {"fields": ("last_name", "first_name")}),
        ("Права Django", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Служебные даты", {"fields": ("last_login", "date_joined")}),
    )

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    @admin.display(description="Сотрудник", ordering="last_name")
    def employee_name(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.display_name if profile else obj.get_full_name() or obj.username

    @admin.display(description="Роль")
    def employee_role(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "-"

    @admin.display(description="Активация", boolean=True)
    def activation_state(self, obj):
        profile = getattr(obj, "profile", None)
        return False if profile and profile.needs_activation else True

    @admin.display(description="В сети", boolean=True)
    def online_state(self, obj):
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.is_online)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not isinstance(form, EmployeeCreationForm):
            return
        profile, _ = UserProfile.objects.get_or_create(user=form.instance)
        profile.role = form.cleaned_data["role"]
        profile.middle_name = form.cleaned_data.get("middle_name", "")
        profile.save()
        profile.allowed_organs.set(form.cleaned_data["allowed_organs"])
        profile.allowed_departments.set(form.cleaned_data["allowed_departments"])
