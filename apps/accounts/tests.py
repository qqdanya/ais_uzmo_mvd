from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.directory.models import Department, TerritorialOrgan

from .models import UserProfile


class AccountFoundationTests(TestCase):
    def test_profile_display_name_uses_last_name_and_initials(self):
        User = get_user_model()
        user = User.objects.create_user("petrov", first_name="Алексей", last_name="Петров", password="pass12345")
        profile = UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, middle_name="Сергеевич")

        self.assertEqual(profile.display_name, "Петров А.С.")

    def test_activation_sets_password_and_clears_activation_code(self):
        User = get_user_model()
        user = User.objects.create_user("newuser", first_name="Иван", last_name="Иванов")
        user.set_unusable_password()
        user.save(update_fields=["password"])
        profile = UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, activation_code="123456")
        Department.objects.create(name="ТМЦ", slug="tmc", order_number=1)

        response = self.client.post(
            reverse("account_activate"),
            {
                "username": "newuser",
                "activation_code": "123456",
                "password1": "StrongPass12345",
                "password2": "StrongPass12345",
            },
        )

        self.assertRedirects(response, reverse("login"))
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(user.check_password("StrongPass12345"))
        self.assertEqual(profile.activation_code, "")

    def test_profile_generates_activation_code_for_unusable_password(self):
        User = get_user_model()
        user = User.objects.create_user("pending")
        user.set_unusable_password()
        user.save(update_fields=["password"])

        profile = UserProfile.objects.create(user=user)

        self.assertTrue(profile.activation_code)
        self.assertEqual(len(profile.activation_code), 6)
        self.assertTrue(profile.activation_code.isdigit())

    def test_admin_add_user_creates_employee_profile_without_password(self):
        User = get_user_model()
        admin = User.objects.create_superuser("admin", password="pass12345")
        UserProfile.objects.create(user=admin, role=UserProfile.Role.ADMIN)
        department = Department.objects.create(name="ТМЦ", slug="tmc", order_number=1)
        organ = TerritorialOrgan.objects.create(name="Тестовый орган", order_number=1)
        self.client.login(username="admin", password="pass12345")

        form_response = self.client.get(reverse("admin:auth_user_add"))

        self.assertContains(form_response, "Фамилия")
        self.assertContains(form_response, "Имя")
        self.assertContains(form_response, "Отчество")
        self.assertContains(form_response, "Отделы")
        self.assertContains(form_response, "Территориальные органы")
        self.assertNotContains(form_response, 'name="password1"')

        response = self.client.post(
            reverse("admin:auth_user_add"),
            {
                "last_name": "Петров",
                "first_name": "Алексей",
                "middle_name": "Сергеевич",
                "username": "petrov",
                "role": UserProfile.Role.OPERATOR,
                "allowed_organs": [str(organ.pk)],
                "allowed_departments": [str(department.pk)],
                "is_active": "on",
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="petrov")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.profile.display_name, "Петров А.С.")
        self.assertTrue(user.profile.activation_code)
        self.assertEqual(list(user.profile.allowed_departments.all()), [department])
        self.assertEqual(list(user.profile.allowed_organs.all()), [organ])
