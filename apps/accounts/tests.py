from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.directory.models import Department, TerritorialOrgan

from .models import UserProfile


class AccountFoundationTests(TestCase):
    def test_profile_display_name_uses_last_name_and_initials(self):
        User = get_user_model()
        user = User.objects.create_user("petrov", first_name="Алексей", last_name="Петров", password="pass12345")
        profile = UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, middle_name="Сергеевич")

        self.assertEqual(profile.display_name, "Петров А.С.")
        self.assertEqual(profile.full_display_name, "Петров Алексей Сергеевич")

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

    def test_profile_online_window_is_one_minute(self):
        User = get_user_model()
        user = User.objects.create_user("operator", password="pass12345")
        profile = UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)

        profile.last_seen_at = timezone.now() - timezone.timedelta(seconds=50)
        self.assertTrue(profile.is_online)

        profile.last_seen_at = timezone.now() - timezone.timedelta(seconds=70)
        self.assertFalse(profile.is_online)

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

    def test_custom_admin_panel_is_available_to_admin(self):
        User = get_user_model()
        admin = User.objects.create_superuser("admin", password="pass12345")
        UserProfile.objects.create(user=admin, role=UserProfile.Role.ADMIN)
        Department.objects.create(name="ТМЦ", slug="tmc", order_number=1)
        TerritorialOrgan.objects.create(name="Тестовый орган", order_number=1)
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("admin_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-command-page")
        self.assertContains(response, 'hx-trigger="every 30s"')
        self.assertContains(response, reverse("audit_log"))
        self.assertContains(response, reverse("admin:index"))

    def test_custom_admin_panel_is_forbidden_to_operator(self):
        User = get_user_model()
        user = User.objects.create_user("operator", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("admin_panel"))

        self.assertEqual(response.status_code, 403)

    def test_custom_admin_panel_hx_refresh_returns_only_panel(self):
        User = get_user_model()
        admin = User.objects.create_superuser("admin", password="pass12345")
        UserProfile.objects.create(user=admin, role=UserProfile.Role.ADMIN)
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("admin_panel"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-command-panel")
        self.assertNotContains(response, "app-footer")
        self.assertNotContains(response, "<main")

    def test_presence_ping_updates_last_seen(self):
        User = get_user_model()
        user = User.objects.create_user("operator", password="pass12345")
        profile = UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)
        old_seen = timezone.now() - timezone.timedelta(minutes=10)
        profile.last_seen_at = old_seen
        profile.save(update_fields=["last_seen_at"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(reverse("presence_ping"))

        self.assertEqual(response.status_code, 204)
        profile.refresh_from_db()
        self.assertGreater(profile.last_seen_at, old_seen)

    def test_presence_ping_requires_login(self):
        response = self.client.post(reverse("presence_ping"))

        self.assertEqual(response.status_code, 302)

    def test_authenticated_layout_contains_presence_url(self):
        User = get_user_model()
        user = User.objects.create_user("operator", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, f'data-presence-url="{reverse("presence_ping")}"')

    def test_user_menu_admin_link_points_to_custom_panel(self):
        User = get_user_model()
        admin = User.objects.create_superuser("admin", password="pass12345")
        UserProfile.objects.create(user=admin, role=UserProfile.Role.ADMIN)
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, f'href="{reverse("admin_panel")}"')
