from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan

from .forms import ACTIVATION_MAX_ATTEMPTS, LOGIN_MAX_ATTEMPTS
from .models import UserProfile


class AccountFoundationTests(TestCase):
    def test_full_page_templates_define_browser_titles_without_dash_separators(self):
        template_root = Path(settings.BASE_DIR) / "templates"
        missing_titles = []

        for template_path in template_root.rglob("*.html"):
            source = template_path.read_text(encoding="utf-8")
            if '{% extends "base.html" %}' not in source:
                continue
            if "{% block title %}" not in source:
                missing_titles.append(template_path.relative_to(template_root).as_posix())
                continue
            title_line = next(line for line in source.splitlines() if "{% block title %}" in line)
            self.assertNotIn("—", title_line)
            self.assertNotIn("–", title_line)

        self.assertEqual(missing_titles, [])

    def test_account_pages_render_specific_browser_titles(self):
        self.assertContains(self.client.get(reverse("login")), "<title>Вход | АИС УЗМО</title>", html=True)
        self.assertContains(
            self.client.get(reverse("account_activate")),
            "<title>Активация учётной записи | АИС УЗМО</title>",
            html=True,
        )

        User = get_user_model()
        user = User.objects.create_user("title-check", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)
        self.client.force_login(user)

        self.assertContains(
            self.client.get(reverse("password_change")),
            "<title>Смена пароля | АИС УЗМО</title>",
            html=True,
        )
        self.assertContains(
            self.client.get(reverse("password_change_done")),
            "<title>Пароль изменён | АИС УЗМО</title>",
            html=True,
        )

    def test_password_change_writes_safe_audit_event(self):
        User = get_user_model()
        user = User.objects.create_user("password-owner", password="OldStrongPass123")
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN)
        self.client.force_login(user)

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "OldStrongPass123",
                "new_password1": "NewStrongPass456",
                "new_password2": "NewStrongPass456",
            },
        )

        self.assertRedirects(response, reverse("password_change_done"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewStrongPass456"))
        log = AuditLog.objects.get(event_type=AuditLog.EventType.PASSWORD_CHANGED)
        self.assertEqual(log.user, user)
        self.assertEqual(log.model_name, "User")
        self.assertEqual(log.object_id, str(user.pk))
        self.assertIsNone(log.old_values)
        self.assertEqual(log.new_values, {"audit_event": AuditLog.EventType.PASSWORD_CHANGED})
        detail = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(detail, "Пользователь изменил пароль")
        self.assertNotContains(detail, "Изменённые поля")
        self.assertNotContains(detail, "OldStrongPass123")
        self.assertNotContains(detail, "NewStrongPass456")

    def test_password_change_rejects_current_password_without_audit_event(self):
        User = get_user_model()
        user = User.objects.create_user("same-password-owner", password="CurrentStrongPass123")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)
        self.client.force_login(user)

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "CurrentStrongPass123",
                "new_password1": "CurrentStrongPass123",
                "new_password2": "CurrentStrongPass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Новый пароль должен отличаться от текущего.")
        user.refresh_from_db()
        self.assertTrue(user.check_password("CurrentStrongPass123"))
        self.assertFalse(AuditLog.objects.filter(event_type=AuditLog.EventType.PASSWORD_CHANGED).exists())

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
        log = AuditLog.objects.get(event_type=AuditLog.EventType.ACCOUNT_ACTIVATED)
        self.assertEqual(log.old_values, {"activation_status": "needs_activation"})
        self.assertEqual(
            log.new_values,
            {
                "audit_event": AuditLog.EventType.ACCOUNT_ACTIVATED,
                "activation_status": "activated",
            },
        )
        self.assertNotIn("password", log.new_values)
        self.assertNotIn("activation_code", log.new_values)

    def test_activation_locks_out_after_too_many_wrong_codes(self):
        User = get_user_model()
        user = User.objects.create_user("bruteforced", first_name="Иван", last_name="Иванов")
        user.set_unusable_password()
        user.save(update_fields=["password"])
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, activation_code="123456")

        payload = {
            "username": "bruteforced",
            "activation_code": "000000",
            "password1": "StrongPass12345",
            "password2": "StrongPass12345",
        }
        for _ in range(ACTIVATION_MAX_ATTEMPTS):
            response = self.client.post(reverse("account_activate"), payload)
            self.assertContains(response, "Неверный код активации.")

        response = self.client.post(reverse("account_activate"), {**payload, "activation_code": "123456"})

        self.assertContains(response, "Слишком много попыток активации")
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_login_locks_out_after_too_many_wrong_passwords(self):
        User = get_user_model()
        user = User.objects.create_user("loginbrute", password="CorrectPass123")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)

        for _ in range(LOGIN_MAX_ATTEMPTS):
            response = self.client.post(reverse("login"), {"username": "loginbrute", "password": "wrong-password"})
            self.assertFalse(response.wsgi_request.user.is_authenticated)

        response = self.client.post(reverse("login"), {"username": "loginbrute", "password": "CorrectPass123"})

        self.assertIn("Слишком много попыток входа", str(response.context["form"].errors))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_succeeds_normally_below_the_attempt_limit(self):
        User = get_user_model()
        user = User.objects.create_user("normallogin", password="CorrectPass123")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR)

        self.client.post(reverse("login"), {"username": "normallogin", "password": "wrong-password"})
        response = self.client.post(reverse("login"), {"username": "normallogin", "password": "CorrectPass123"})

        self.assertTrue(response.wsgi_request.user.is_authenticated)

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
        self.assertContains(response, 'id="admin-panel-refresh"')
        self.assertContains(response, f'data-summary-url="{reverse("admin_summary_data")}"')
        self.assertContains(response, 'id="admin-summary-data"')
        self.assertContains(response, '/static/js/admin_summary.js')
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
