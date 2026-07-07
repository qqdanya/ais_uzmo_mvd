import json
import shutil
import tempfile
from io import BytesIO
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import FireExtinguisher, NeedStatus, RequestNumberRegistry, RequestPhotoLink, TmcRequest, VehicleRepairRequest

from .admin_thresholds import _THRESHOLDS_CACHE, get_dashboard_thresholds
from .models import UserProfile


class AdminPanelTestMixin:
    def setUp(self):
        self.User = get_user_model()
        self.department_tmc = Department.objects.create(name="ТМЦ", slug="tmc", order_number=1)
        self.department_transport = Department.objects.create(name="Транспорт", slug="transport", order_number=2)
        self.organ = TerritorialOrgan.objects.create(name="Тестовый территориальный орган", order_number=1)
        self.other_organ = TerritorialOrgan.objects.create(name="Другой территориальный орган", order_number=2)
        self.admin = self.User.objects.create_superuser(
            "admin",
            password="pass12345",
            first_name="Алексей",
            last_name="Руководитель",
        )
        self.admin_profile = UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN)
        self.admin_profile.allowed_organs.set([self.organ, self.other_organ])
        self.admin_profile.allowed_departments.set([self.department_tmc, self.department_transport])
        self.operator = self.User.objects.create_user(
            "operator",
            password="pass12345",
            first_name="Олег",
            last_name="Оператор",
        )
        self.operator_profile = UserProfile.objects.create(user=self.operator, role=UserProfile.Role.OPERATOR)
        self.operator_profile.allowed_organs.set([self.organ])
        self.operator_profile.allowed_departments.set([self.department_tmc])

    def login_admin(self):
        self.client.login(username="admin", password="pass12345")

    def login_operator(self):
        self.client.login(username="operator", password="pass12345")


class AdminPanelEndpointTests(AdminPanelTestMixin, TestCase):
    def test_core_control_pages_are_available_to_admin(self):
        self.login_admin()
        endpoints = [
            "admin_panel",
            "admin_requests_panel",
            "admin_organs_panel",
            "admin_departments_panel",
            "admin_assets_panel",
            "admin_employees_panel",
            "admin_threshold_settings",
        ]

        expected_tabs = {
            "admin_requests_panel": "requests",
            "admin_organs_panel": "organs",
            "admin_departments_panel": "departments",
            "admin_assets_panel": "assets",
            "admin_employees_panel": "employees",
            "admin_threshold_settings": "settings",
        }
        for name in endpoints:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                if name in expected_tabs:
                    self.assertEqual(response.context["active_tab"], expected_tabs[name])

    def test_summary_data_returns_json_for_admin(self):
        self.login_admin()

        response = self.client.get(reverse("admin_summary_data"), {"org_metric": "done"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("period", payload)
        self.assertIn("selected_organs", payload)
        self.assertIn("selected_organs_count", payload)
        self.assertIn("kpi", payload)
        self.assertIn("dynamics", payload)
        self.assertIn("org_chart", payload)
        self.assertIn("department_load", payload)
        self.assertIn("attention_requests", payload)
        self.assertIn("request_stale_workdays", payload)
        for key in ("total", "in_work", "done", "rejected", "stale"):
            self.assertIn(key, payload["kpi"])


    def test_attention_requests_include_detail_url(self):
        self.login_admin()
        stale_date = timezone.localdate() - timedelta(days=45)
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="99",
            request_date=stale_date,
            status=NeedStatus.IN_WORK,
        )

        response = self.client.get(reverse("admin_summary_data"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["attention_requests"])
        self.assertEqual(
            payload["attention_requests"][0]["detail_url"],
            reverse("admin_request_detail", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}),
        )

    def test_summary_data_respects_selected_organ_filter(self):
        self.login_admin()
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="15",
            request_date=today,
        )
        TmcRequest.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            request_number="16",
            request_date=today,
        )

        response = self.client.get(
            reverse("admin_summary_data"),
            {"period": "all", "organ_ids": [str(self.organ.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_organs"], [self.organ.pk])
        self.assertEqual(payload["selected_organs_count"], 1)
        self.assertEqual(payload["kpi"]["total"], 1)
        self.assertEqual(payload["kpi"]["in_work"], 1)
        self.assertEqual(payload["org_chart"], [{"id": self.organ.pk, "name": self.organ.name, "value": 1, "percent": 100}])

    def test_control_pages_are_forbidden_to_operator(self):
        self.login_operator()

        for name in ("admin_panel", "admin_employees_panel", "admin_assets_panel", "admin_threshold_settings"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 403)

    def test_profile_admin_without_staff_can_open_control_but_not_django_admin(self):
        profile_admin = self.User.objects.create_user("profile_admin", password="pass12345", is_staff=False)
        UserProfile.objects.create(user=profile_admin, role=UserProfile.Role.ADMIN)
        self.client.login(username="profile_admin", password="pass12345")

        control_response = self.client.get(reverse("admin_panel"))
        django_admin_response = self.client.get(reverse("admin:index"))

        self.assertEqual(control_response.status_code, 200)
        self.assertEqual(django_admin_response.status_code, 302)

    def test_database_tables_button_is_visible_only_to_leader(self):
        profile_admin = self.User.objects.create_user("profile_admin", password="pass12345", is_staff=False)
        UserProfile.objects.create(user=profile_admin, role=UserProfile.Role.ADMIN)
        self.client.login(username="profile_admin", password="pass12345")

        profile_admin_response = self.client.get(reverse("admin_panel"))
        self.assertEqual(profile_admin_response.status_code, 200)
        self.assertNotContains(profile_admin_response, "Таблицы БД")
        self.assertNotContains(profile_admin_response, f'href="{reverse("admin:index")}"')

        self.client.logout()
        self.login_admin()
        leader_response = self.client.get(reverse("admin_panel"))
        self.assertContains(leader_response, "Таблицы БД")
        self.assertContains(leader_response, f'href="{reverse("admin:index")}"')

    def test_django_admin_is_not_available_to_operator_or_observer(self):
        observer = self.User.objects.create_user("observer", password="pass12345", is_staff=False)
        UserProfile.objects.create(user=observer, role=UserProfile.Role.OBSERVER)

        for username in ("operator", "observer"):
            with self.subTest(username=username):
                self.client.logout()
                self.client.login(username=username, password="pass12345")
                response = self.client.get(reverse("admin:index"))
                self.assertEqual(response.status_code, 302)

    def test_control_panel_requires_login_and_admin_role(self):
        self.client.logout()
        login_response = self.client.get(reverse("admin_panel"))
        self.assertEqual(login_response.status_code, 302)

        observer = self.User.objects.create_user("observer", password="pass12345")
        UserProfile.objects.create(user=observer, role=UserProfile.Role.OBSERVER)
        self.client.login(username="observer", password="pass12345")
        forbidden_response = self.client.get(reverse("admin_panel"))
        self.assertEqual(forbidden_response.status_code, 403)


class AdminRequestsPanelTests(AdminPanelTestMixin, TestCase):
    def test_requests_panel_filters_by_status_organ_and_search(self):
        self.login_admin()
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="15",
            request_date=today,
            status=NeedStatus.DONE,
            due_date=today,
            comment="бумага для отдела",
        )
        TmcRequest.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            request_number="16",
            request_date=today,
            status=NeedStatus.IN_WORK,
            comment="не должен попасть в выборку",
        )

        response = self.client.get(
            reverse("admin_requests_panel"),
            {"state": "done", "organ_ids": [str(self.organ.pk)], "q": "бумага"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "requests")
        self.assertEqual(response.context["total_count"], 1)
        rows = list(response.context["page"].object_list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["number"], "15")
        self.assertEqual(rows[0]["status"], NeedStatus.DONE)
        self.assertEqual(rows[0]["organ_id"], self.organ.pk)
        self.assertIn(f"Орган: {self.organ.name}", response.context["active_filter_chips"])
        self.assertIn("Поиск: бумага", response.context["active_filter_chips"])
        self.assertIn("Статусы: Исполнено", response.context["active_filter_chips"])


    def test_request_detail_shows_linked_photo_thumbnails(self):
        self.login_admin()
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            updated_by=self.admin,
            request_number="ТМЦ-ФОТО",
            request_date=timezone.localdate(),
            status=NeedStatus.IN_WORK,
            comment="Заявка с фотографией",
        )
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            image=SimpleUploadedFile("detail-proof.png", buffer.getvalue(), content_type="image/png"),
            description="Фотография заявки",
            created_by=self.admin,
            updated_by=self.admin,
        )
        RequestPhotoLink.objects.create(territorial_organ=self.organ, photo=photo, request=request_obj, created_by=self.admin)

        response = self.client.get(reverse("admin_request_detail", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["photo_count"], 1)
        self.assertEqual(len(response.context["attached_photos"]), 1)
        self.assertContains(response, "1")
        self.assertContains(response, "фотография прикреплена")
        self.assertContains(response, "admin-request-photo-thumbnails")
        self.assertContains(response, "admin-request-photo-thumb")
        self.assertContains(response, "detail-proof")

    def test_requests_panel_department_filter_limits_request_tables(self):
        self.login_admin()
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТМЦ-1",
            request_date=today,
        )
        VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТР-1",
            request_date=today,
        )

        response = self.client.get(reverse("admin_requests_panel"), {"department": "tmc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["filters"]["department"], "tmc")
        self.assertEqual(response.context["total_count"], 1)
        rows = list(response.context["page"].object_list)
        self.assertEqual([row["table_key"] for row in rows], ["tmc-requests"])
        self.assertEqual(rows[0]["number"], "ТМЦ-1")
        self.assertIn("Отделы: ТМЦ", response.context["active_filter_chips"])


class AdminOrgansDepartmentsPanelTests(AdminPanelTestMixin, TestCase):
    def test_organs_panel_filters_by_search_department_and_request_status(self):
        self.login_admin()
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТМЦ-15",
            request_date=today,
            status=NeedStatus.IN_WORK,
        )
        VehicleRepairRequest.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            request_number="ТР-16",
            request_date=today,
            status=NeedStatus.IN_WORK,
        )

        response = self.client.get(
            reverse("admin_organs_panel"),
            {"q": "Тестовый", "department": "tmc", "request_status": "in_work"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "organs")
        self.assertEqual(response.context["filters"]["departments"], ["tmc"])
        self.assertEqual(response.context["filters"]["request_statuses"], ["in_work"])
        rows = list(response.context["page"].object_list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organ"], self.organ)
        self.assertEqual(rows[0]["total"], 1)
        self.assertEqual(rows[0]["in_work"], 1)
        self.assertIn("Отделы: ТМЦ", response.context["active_filter_chips"])
        self.assertIn("Статусы заявок: В работе", response.context["active_filter_chips"])
        self.assertIn("Поиск: Тестовый", response.context["active_filter_chips"])

    def test_organs_panel_search_uses_database_prefilter_with_cyrillic_case_variants(self):
        self.login_admin()

        response = self.client.get(reverse("admin_organs_panel"), {"q": "тестовый"})

        self.assertEqual(response.status_code, 200)
        rows = list(response.context["page"].object_list)
        self.assertEqual([row["organ"] for row in rows], [self.organ])

    def test_departments_panel_search_uses_database_prefilter_with_cyrillic_case_variants(self):
        self.login_admin()

        response = self.client.get(reverse("admin_departments_panel"), {"q": "тмц"})

        self.assertEqual(response.status_code, 200)
        rows = list(response.context["page"].object_list)
        self.assertEqual([row["slug"] for row in rows], ["tmc"])

    def test_departments_panel_respects_selected_organ_and_request_status(self):
        self.login_admin()
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТМЦ-15",
            request_date=today,
            status=NeedStatus.IN_WORK,
        )
        TmcRequest.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            request_number="ТМЦ-16",
            request_date=today,
            status=NeedStatus.IN_WORK,
        )
        VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТР-17",
            request_date=today,
            status=NeedStatus.DONE,
            completed_at=today,
        )

        response = self.client.get(
            reverse("admin_departments_panel"),
            {"organ_ids": [str(self.organ.pk)], "request_status": "in_work"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "departments")
        self.assertEqual(response.context["selected_organ_ids"], {self.organ.pk})
        self.assertEqual(response.context["filters"]["request_statuses"], ["in_work"])
        rows_by_slug = {row["slug"]: row for row in response.context["page"].object_list}
        self.assertEqual(rows_by_slug["tmc"]["total"], 1)
        self.assertEqual(rows_by_slug["tmc"]["in_work"], 1)
        self.assertEqual(rows_by_slug["transport"]["total"], 0)
        self.assertIn(f"Орган: {self.organ.name}", response.context["active_filter_chips"])
        self.assertIn("Статусы заявок: В работе", response.context["active_filter_chips"])


class AdminEmployeesPanelTests(AdminPanelTestMixin, TestCase):
    def test_employees_panel_filters_by_query_and_exposes_presence_url(self):
        self.login_admin()
        target = self.User.objects.create_user("ivanov", first_name="Иван", last_name="Иванов")
        profile = UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)
        profile.allowed_organs.set([self.organ])
        profile.allowed_departments.set([self.department_tmc])

        response = self.client.get(reverse("admin_employees_panel"), {"q": "Иванов"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "employees")
        self.assertEqual(response.context["presence_data_url"], reverse("admin_employees_presence_data"))
        self.assertContains(response, "Иванов")
        self.assertContains(response, "admin-employees-page")

    def test_employees_panel_department_filter_excludes_empty_department_access(self):
        self.login_admin()
        unrestricted = self.User.objects.create_user("all_depts", first_name="Анна", last_name="Всеотделы")
        unrestricted_profile = UserProfile.objects.create(user=unrestricted, role=UserProfile.Role.OPERATOR)
        unrestricted_profile.allowed_organs.set([self.organ])

        transport_only = self.User.objects.create_user("transport_only", first_name="Тимур", last_name="Транспорт")
        transport_profile = UserProfile.objects.create(user=transport_only, role=UserProfile.Role.OPERATOR)
        transport_profile.allowed_departments.set([self.department_transport])
        transport_profile.allowed_organs.set([self.organ])

        response = self.client.get(reverse("admin_employees_panel"), {"department": "tmc"})

        self.assertEqual(response.status_code, 200)
        usernames = {row["user"].username for row in response.context["employees"]}
        self.assertNotIn("all_depts", usernames)
        self.assertNotIn("transport_only", usernames)
        self.assertIn("Отделы: ТМЦ", response.context["active_filter_chips"])

    def test_employee_empty_department_permissions_are_displayed_as_no_department_access(self):
        self.login_admin()
        target = self.User.objects.create_user("all_department_access", first_name="Артём", last_name="Полный")
        profile = UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)
        profile.allowed_organs.set([self.organ])

        response = self.client.get(reverse("admin_employee_detail", kwargs={"pk": target.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["departments_summary"], "Отделы не выбраны")
        self.assertFalse(response.context["all_departments"])
        self.assertTrue(response.context["no_departments"])
        self.assertContains(response, "Отделы не выбраны")

    def test_employee_create_creates_unactivated_user_with_permissions_and_audit(self):
        self.login_admin()

        response = self.client.post(
            reverse("admin_employee_create"),
            {
                "last_name": "Петров",
                "first_name": "Павел",
                "middle_name": "Иванович",
                "username": "petrov",
                "role": UserProfile.Role.OPERATOR,
                "allowed_departments": [str(self.department_tmc.pk)],
                "allowed_organs": [str(self.organ.pk)],
                "is_active": "on",
            },
        )

        user = self.User.objects.get(username="petrov")
        self.assertRedirects(response, reverse("admin_employee_detail", kwargs={"pk": user.pk}))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.profile.activation_code)
        self.assertEqual(user.profile.middle_name, "Иванович")
        self.assertEqual(list(user.profile.allowed_departments.all()), [self.department_tmc])
        self.assertEqual(list(user.profile.allowed_organs.all()), [self.organ])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(user.pk)).exists())

    def test_employee_actions_block_unblock_and_reset_activation(self):
        self.login_admin()
        target = self.User.objects.create_user("blocked_user", password="pass12345", is_active=True)
        UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)

        block_response = self.client.post(reverse("admin_employee_action", kwargs={"pk": target.pk}), {"action": "block"})
        target.refresh_from_db()
        self.assertRedirects(block_response, reverse("admin_employee_detail", kwargs={"pk": target.pk}))
        self.assertFalse(target.is_active)

        unblock_response = self.client.post(reverse("admin_employee_action", kwargs={"pk": target.pk}), {"action": "unblock"})
        target.refresh_from_db()
        self.assertRedirects(unblock_response, reverse("admin_employee_detail", kwargs={"pk": target.pk}))
        self.assertTrue(target.is_active)

        reset_response = self.client.post(reverse("admin_employee_action", kwargs={"pk": target.pk}), {"action": "reset_activation"})
        target.refresh_from_db()
        self.assertRedirects(reset_response, reverse("admin_employee_detail", kwargs={"pk": target.pk}))
        self.assertFalse(target.has_usable_password())
        self.assertTrue(target.profile.activation_code)

    def test_employee_actions_cannot_block_or_reset_self(self):
        self.login_admin()
        self.assertTrue(self.admin.has_usable_password())

        block_response = self.client.post(reverse("admin_employee_action", kwargs={"pk": self.admin.pk}), {"action": "block"})
        self.admin.refresh_from_db()
        self.assertRedirects(block_response, reverse("admin_employee_detail", kwargs={"pk": self.admin.pk}))
        self.assertTrue(self.admin.is_active)

        reset_response = self.client.post(reverse("admin_employee_action", kwargs={"pk": self.admin.pk}), {"action": "reset_activation"})
        self.admin.refresh_from_db()
        self.assertRedirects(reset_response, reverse("admin_employee_detail", kwargs={"pk": self.admin.pk}))
        self.assertTrue(self.admin.has_usable_password())


    def test_employee_create_form_defaults_all_organs_and_add_button(self):
        self.login_admin()

        response = self.client.get(reverse("admin_employee_create"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["submit_label"], "Добавить сотрудника")
        self.assertEqual(
            set(response.context["selected_organs"]),
            {str(self.organ.pk), str(self.other_organ.pk)},
        )
        self.assertContains(response, "Добавить сотрудника")
        self.assertNotContains(response, "Создать сотрудника")

    def test_employee_create_form_renders_decimal_organ_numbers_without_scientific_notation(self):
        self.login_admin()
        TerritorialOrgan.objects.create(name="Десятый орган", order_number=Decimal("10.00"))

        response = self.client.get(reverse("admin_employee_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "10. Десятый орган")
        self.assertNotContains(response, "1E+1. Десятый орган")

    def test_employee_create_form_exposes_existing_usernames_for_auto_login(self):
        self.login_admin()
        self.User.objects.create_user("petrov")

        response = self.client.get(reverse("admin_employee_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-existing-usernames"')
        self.assertIn("petrov", response.context["existing_usernames"])

    def test_employee_create_requires_first_and_last_name(self):
        self.login_admin()

        response = self.client.post(
            reverse("admin_employee_create"),
            {
                "username": "nameless",
                "role": UserProfile.Role.OPERATOR,
                "allowed_organs": [str(self.organ.pk)],
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "last_name", "Укажите фамилию сотрудника.")
        self.assertFormError(response.context["form"], "first_name", "Укажите имя сотрудника.")
        self.assertFalse(self.User.objects.filter(username="nameless").exists())

    def test_employee_create_generates_unique_transliterated_username(self):
        self.login_admin()
        self.User.objects.create_user("petrov")
        self.User.objects.create_user("petrov_pavel")

        response = self.client.post(
            reverse("admin_employee_create"),
            {
                "last_name": "Петров",
                "first_name": "Павел",
                "middle_name": "Иванович",
                "username": "petrov",
                "username_auto": "True",
                "role": UserProfile.Role.OPERATOR,
                "allowed_departments": [str(self.department_tmc.pk)],
                "allowed_organs": [str(self.organ.pk)],
                "is_active": "on",
            },
        )

        user = self.User.objects.get(username="petrov_pavel_ivanovich")
        self.assertRedirects(response, reverse("admin_employee_detail", kwargs={"pk": user.pk}))
        self.assertEqual(user.last_name, "Петров")
        self.assertEqual(user.first_name, "Павел")

    def test_employee_username_script_uses_existing_usernames_before_adding_name_parts(self):
        script = Path("static/js/employee_form.js").read_text(encoding="utf-8")

        self.assertIn("employee-existing-usernames", script)
        self.assertIn("const candidates = [last];", script)
        self.assertIn("const available = candidates.find((candidate) => !taken.has(candidate));", script)
        self.assertNotIn("if (first && middle) return `${last}_${first}_${middle}`;", script)

    def test_employee_role_dropdown_closes_after_radio_choice(self):
        script = Path("static/js/admin_multiselect.js").read_text(encoding="utf-8")

        self.assertIn('input.type === "radio"', script)
        self.assertIn("bootstrap.Dropdown.getOrCreateInstance(trigger).hide()", script)

    def test_superuser_can_delete_employee_from_database(self):
        self.login_admin()
        target = self.User.objects.create_user("delete_me", first_name="Денис", last_name="Удаляемый")
        UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)

        response = self.client.post(reverse("admin_employee_action", kwargs={"pk": target.pk}), {"action": "delete"})

        self.assertRedirects(response, reverse("admin_employees_panel"))
        self.assertFalse(self.User.objects.filter(pk=target.pk).exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.DELETE,
                model_name="User",
                object_id=str(target.pk),
                new_values__audit_event="employee_deleted",
            ).exists()
        )

    def test_regular_admin_cannot_delete_employee_from_database(self):
        regular_admin = self.User.objects.create_user("regular_admin", password="pass12345")
        UserProfile.objects.create(user=regular_admin, role=UserProfile.Role.ADMIN)
        target = self.User.objects.create_user("delete_denied")
        UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)
        self.client.login(username="regular_admin", password="pass12345")

        response = self.client.post(reverse("admin_employee_action", kwargs={"pk": target.pk}), {"action": "delete"})

        self.assertRedirects(response, reverse("admin_employee_detail", kwargs={"pk": target.pk}))
        self.assertTrue(self.User.objects.filter(pk=target.pk).exists())

    def test_employee_presence_data_updates_kpis_and_rows(self):
        self.login_admin()
        self.operator_profile.last_seen_at = timezone.now()
        self.operator_profile.save(update_fields=["last_seen_at"])

        response = self.client.get(reverse("admin_employees_presence_data"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("generated_at", payload)
        self.assertGreaterEqual(payload["kpis"]["total"], 2)
        self.assertGreaterEqual(payload["kpis"]["online"], 1)
        row = next(item for item in payload["employees"] if item["id"] == self.operator.pk)
        self.assertEqual(row["activity_state"], "online")
        self.assertEqual(row["activity_label"], "Онлайн")


class AdminAssetsPanelTests(AdminPanelTestMixin, TestCase):
    def test_assets_panel_and_details_expose_stale_material_state(self):
        self.login_admin()
        FireExtinguisher.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            state_date=timezone.localdate() - timezone.timedelta(days=90),
            required_count=10,
            available_count=10,
            expiry_date=timezone.localdate() + timezone.timedelta(days=365),
            writeoff_count=0,
        )

        panel_response = self.client.get(reverse("admin_assets_panel"))
        category_response = self.client.get(reverse("admin_asset_category_detail", kwargs={"category_key": "fire-extinguishers"}))
        organ_response = self.client.get(reverse("admin_asset_organ_summary", kwargs={"organ_id": self.organ.pk}))
        detail_response = self.client.get(reverse("admin_asset_organ_detail", kwargs={"category_key": "fire-extinguishers", "organ_id": self.organ.pk}))

        self.assertEqual(panel_response.status_code, 200)
        self.assertEqual(category_response.status_code, 200)
        self.assertEqual(organ_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(panel_response.context["active_tab"], "assets")
        self.assertTrue(any(item["key"] == "stale" and item["count"] >= 1 for item in panel_response.context["status_tabs"]))
        self.assertEqual(category_response.context["summary"]["stale_count"], 1)
        self.assertEqual(detail_response.context["cell"]["status"], "stale")

    def test_assets_panel_filters_by_category_status_and_search(self):
        self.login_admin()
        today = timezone.localdate()
        FireExtinguisher.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            state_date=today,
            required_count=10,
            available_count=10,
            expiry_date=today + timezone.timedelta(days=365),
            writeoff_count=0,
        )
        FireExtinguisher.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            state_date=today,
            required_count=10,
            available_count=4,
            expiry_date=today + timezone.timedelta(days=365),
            writeoff_count=0,
        )

        response = self.client.get(
            reverse("admin_assets_panel"),
            {
                "category": "fire-extinguishers",
                "asset_status": "danger",
                "q": "Другой",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "assets")
        self.assertEqual([item["key"] for item in response.context["matrix_categories"]], ["fire-extinguishers"])
        self.assertEqual(response.context["total_count"], 1)
        rows = list(response.context["page"].object_list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organ"], self.other_organ)
        self.assertEqual(rows[0]["danger"], 1)
        self.assertIn("Категории: Огнетушители", response.context["active_filter_chips"])

    def test_assets_panel_search_uses_database_prefilter_with_cyrillic_case_variants(self):
        self.login_admin()
        today = timezone.localdate()
        FireExtinguisher.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            state_date=today,
            required_count=10,
            available_count=10,
            expiry_date=today + timezone.timedelta(days=365),
            writeoff_count=0,
        )

        response = self.client.get(reverse("admin_assets_panel"), {"q": "другой"})

        self.assertEqual(response.status_code, 200)
        rows = list(response.context["page"].object_list)
        self.assertEqual([row["organ"] for row in rows], [self.other_organ])
        self.assertIn("Поиск: другой", response.context["active_filter_chips"])
        self.assertNotIn("Состояния: Проблемные", response.context["active_filter_chips"])

    def test_asset_category_detail_filters_by_status_without_changing_summary(self):
        self.login_admin()
        today = timezone.localdate()
        FireExtinguisher.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            state_date=today,
            required_count=10,
            available_count=10,
            expiry_date=today + timezone.timedelta(days=365),
            writeoff_count=0,
        )
        FireExtinguisher.objects.create(
            territorial_organ=self.other_organ,
            created_by=self.admin,
            state_date=today,
            required_count=10,
            available_count=3,
            expiry_date=today + timezone.timedelta(days=365),
            writeoff_count=0,
        )

        response = self.client.get(
            reverse("admin_asset_category_detail", kwargs={"category_key": "fire-extinguishers"}),
            {"asset_status": "danger"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["data_count"], 2)
        self.assertEqual(response.context["summary"]["danger_count"], 1)
        rows = list(response.context["page"].object_list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["organ"], self.other_organ)
        self.assertEqual(rows[0]["danger"], 1)


class AdminSettingsPanelTests(AdminPanelTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.mkdtemp(prefix="ais-thresholds-")
        self.thresholds_file = Path(self.temp_dir) / "dashboard_thresholds.json"
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.addCleanup(self.clear_threshold_cache)
        self.clear_threshold_cache()

    def clear_threshold_cache(self):
        _THRESHOLDS_CACHE["mtime"] = None
        _THRESHOLDS_CACHE["values"] = None

    def test_settings_post_saves_valid_thresholds(self):
        self.login_admin()

        with self.settings(ADMIN_THRESHOLDS_FILE=str(self.thresholds_file)):
            response = self.client.post(
                reverse("admin_threshold_settings"),
                {
                    "request_stale_workdays": "21",
                    "asset_stale_days": "75",
                },
            )
            values = get_dashboard_thresholds()

        self.assertRedirects(response, reverse("admin_threshold_settings"))
        self.assertEqual(values["request_stale_workdays"], 21)
        self.assertEqual(values["asset_stale_days"], 75)
        self.assertEqual(json.loads(self.thresholds_file.read_text(encoding="utf-8"))["asset_stale_days"], 75)

    def test_settings_invalid_values_return_form_errors_without_saving(self):
        self.login_admin()

        with self.settings(ADMIN_THRESHOLDS_FILE=str(self.thresholds_file)):
            response = self.client.post(
                reverse("admin_threshold_settings"),
                {
                    "request_stale_workdays": "0",
                    "asset_stale_days": "not-a-number",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "settings")
        self.assertIn("request_stale_workdays", response.context["settings_errors"])
        self.assertIn("asset_stale_days", response.context["settings_errors"])
        self.assertFalse(self.thresholds_file.exists())
class AdminSelectComponentTests(AdminPanelTestMixin, TestCase):
    def test_admin_multiselect_markup_is_centralized(self):
        project_root = Path(__file__).resolve().parents[2]
        partial_path = project_root / "templates" / "partials" / "admin_multiselect.html"
        self.assertTrue(partial_path.exists())
        self.assertIn("data-admin-multiselect", partial_path.read_text(encoding="utf-8"))

        raw_markup_locations = []
        for template_path in (project_root / "templates" / "admin_panel").rglob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            if '<div class="dropdown admin-multiselect' in content:
                raw_markup_locations.append(str(template_path.relative_to(project_root)))
        self.assertEqual(raw_markup_locations, [])


    def test_single_select_markup_is_centralized(self):
        project_root = Path(__file__).resolve().parents[2]
        partial_path = project_root / "templates" / "partials" / "single_select.html"
        self.assertTrue(partial_path.exists())
        self.assertIn("<select", partial_path.read_text(encoding="utf-8"))

        allowed_raw_select_locations = {
            "templates/partials/table/_summary_actions.html",
            "templates/partials/table/_toolbar.html",
        }
        unexpected_raw_select_locations = []
        for template_path in (project_root / "templates").rglob("*.html"):
            if template_path.name == "single_select.html":
                continue
            content = template_path.read_text(encoding="utf-8")
            relative_path = template_path.relative_to(project_root).as_posix()
            if "<select" in content and relative_path not in allowed_raw_select_locations:
                unexpected_raw_select_locations.append(relative_path)
        self.assertEqual(unexpected_raw_select_locations, [])

    def test_request_photo_sort_uses_shared_custom_select(self):
        project_root = Path(__file__).resolve().parents[2]
        panel_template = project_root / "templates" / "partials" / "request_photo_picker_panel.html"
        panel_content = panel_template.read_text(encoding="utf-8")
        self.assertIn('id="request-photo-sort-input"', panel_content)
        self.assertIn("single_select", panel_content)
        self.assertNotIn("request-photo-sort-select", panel_content)
        self.assertNotIn("data-request-photo-sort", panel_content)

        custom_select_js = (project_root / "static" / "js" / "custom_select.js").read_text(encoding="utf-8")
        self.assertNotIn("request-photo-sort-select", custom_select_js)
        self.assertNotIn("data-request-photo-sort", custom_select_js)

    def test_admin_multiselect_partial_renders_existing_pages(self):
        self.login_admin()
        endpoints = [
            "admin_requests_panel",
            "admin_organs_panel",
            "admin_departments_panel",
            "admin_assets_panel",
            "admin_employees_panel",
            "admin_employee_create",
        ]

        for name in endpoints:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-admin-multiselect")
                self.assertNotContains(response, "request-photo-sort-select")



class RuntimeFileIgnoreTests(TestCase):
    def test_dashboard_threshold_runtime_files_are_ignored(self):
        project_root = Path(__file__).resolve().parents[2]
        gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("dashboard_thresholds.json", gitignore)
        self.assertIn("dashboard_thresholds.json.tmp", gitignore)


class ProductionReadinessDocsTests(TestCase):
    def test_production_env_template_contains_required_security_settings(self):
        project_root = Path(__file__).resolve().parents[2]
        env_template = (project_root / ".env.production.example").read_text(encoding="utf-8")

        for required_name in [
            "SECRET_KEY",
            "DEBUG=False",
            "ALLOWED_HOSTS",
            "DATABASE_URL=postgres://",
            "CSRF_TRUSTED_ORIGINS=https://",
            "SECURE_SSL_REDIRECT=True",
            "SUPERUSER_PASSWORD",
        ]:
            with self.subTest(required_name=required_name):
                self.assertIn(required_name, env_template)

    def test_deploy_checklist_documents_required_commands_and_risks(self):
        project_root = Path(__file__).resolve().parents[2]
        checklist = (project_root / "docs" / "DEPLOY_CHECKLIST.md").read_text(encoding="utf-8")

        for required_text in [
            "check --deploy --settings=config.settings_prod",
            "migrate --settings=config.settings_prod",
            "collectstatic --noinput --settings=config.settings_prod",
            "DATABASE_URL",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "static/vendor/",
            "pip-compile requirements.in --output-file=requirements.txt",
            "X-Accel-Redirect",
        ]:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, checklist)


class VendorStaticTemplateTests(TestCase):
    def test_vendor_assets_are_local_static_files(self):
        project_root = Path(__file__).resolve().parents[2]
        base_template = (project_root / "templates" / "base.html").read_text(encoding="utf-8")
        admin_index = (project_root / "templates" / "admin_panel" / "index.html").read_text(encoding="utf-8")

        for local_path in [
            "vendor/bootstrap/bootstrap.min.css",
            "vendor/bootstrap/bootstrap.bundle.min.js",
            "vendor/bootstrap-icons/bootstrap-icons.css",
            "vendor/htmx/htmx.min.js",
            "vendor/chartjs/chart.umd.min.js",
        ]:
            with self.subTest(local_path=local_path):
                self.assertIn(local_path, base_template + admin_index)
                self.assertTrue((project_root / "static" / local_path).exists())

        for icon_font_path in [
            "vendor/bootstrap-icons/fonts/bootstrap-icons.woff",
            "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
        ]:
            with self.subTest(icon_font_path=icon_font_path):
                self.assertTrue((project_root / "static" / icon_font_path).exists())

    def test_templates_do_not_use_external_cdn_assets(self):
        project_root = Path(__file__).resolve().parents[2]
        template_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (project_root / "templates").rglob("*.html")
        )

        for removed_cdn in [
            "cdn.jsdelivr.net",
            "unpkg.com",
            "bootstrap@5.3.3",
            "bootstrap-icons@1.11.3",
            "htmx.org@1.9.12",
            "chart.js@4.4.3",
        ]:
            with self.subTest(removed_cdn=removed_cdn):
                self.assertNotIn(removed_cdn, template_text)


class TableDataTemplateSplitTests(TestCase):
    expected_partials = {
        "_nested_tabs.html",
        "_toolbar.html",
        "_active_filters.html",
        "_summary.html",
        "_actions.html",
        "_pagination.html",
        "_rows.html",
        "_rows_tmc_product_grouped.html",
        "_rows_organ_grouped.html",
        "_rows_date_grouped.html",
        "_rows_tmc_default.html",
        "_rows_default.html",
    }

    def test_table_data_template_is_delegated_to_partials(self):
        project_root = Path(__file__).resolve().parents[2]
        table_data = project_root / "templates" / "partials" / "table_data.html"
        table_partials_dir = project_root / "templates" / "partials" / "table"

        self.assertLessEqual(len(table_data.read_text(encoding="utf-8").splitlines()), 25)
        existing_partials = {path.name for path in table_partials_dir.glob("*.html")}
        self.assertTrue(self.expected_partials.issubset(existing_partials))

        content = table_data.read_text(encoding="utf-8")
        for partial_name in [
            "_toolbar.html",
            "_active_filters.html",
            "_summary.html",
            "_actions.html",
            "_pagination.html",
            "_rows.html",
        ]:
            with self.subTest(partial=partial_name):
                self.assertIn(f'partials/table/{partial_name}', content)

    def test_table_row_variants_are_split_from_rows_dispatcher(self):
        project_root = Path(__file__).resolve().parents[2]
        rows_dispatcher = project_root / "templates" / "partials" / "table" / "_rows.html"
        content = rows_dispatcher.read_text(encoding="utf-8")

        self.assertLessEqual(len(content.splitlines()), 40)
        self.assertIn("_rows_tmc_product_grouped.html", content)
        self.assertIn("_rows_tmc_default.html", content)
        self.assertIn("_rows_default.html", content)



class FrontendModuleSplitTests(TestCase):
    frontend_globals = {
        "toasts.js": [
            "autoDismissAlerts",
            "initTooltips",
            "showToast",
        ],
        "photo_upload.js": [
            "PhotoUpload",
        ],
        "tmc_products.js": [
            "closeAllTmcProductSuggestions",
            "requestTmcProductSuggestions",
            "chooseTmcProductSuggestion",
            "TmcProducts",
        ],
        "download_preparing.js": [
            "showDownloadPreparingNotice",
            "downloadToken",
            "downloadUrlWithToken",
            "downloadKey",
            "syncActiveDownloadButtons",
            "waitForDownloadStart",
            "markPreparingDownload",
            "DownloadPreparing",
        ],
        "presence_ping.js": [
            "startPresenceHeartbeat",
        ],
        "admin_org_filter.js": [
            "updateAdminFilterOrgBox",
            "initAdminFilterOrgBoxes",
        ],
        "confirm_dialog.js": [
            "ConfirmDialog",
        ],
    }

    app_modules = [
        "app_storage.js",
        "app_dom_utils.js",
        "table_state.js",
        "organ_navigation.js",
        "request_photo_picker.js",
        "layout_panels.js",
        "table_interactions.js",
        "htmx_lifecycle.js",
        "app_events.js",
        "app.js",
    ]

    def project_root(self):
        return Path(__file__).resolve().parents[2]

    def read_static_js(self, filename):
        return (self.project_root() / "static" / "js" / filename).read_text(encoding="utf-8")

    def test_frontend_helpers_are_split_from_app_js(self):
        project_root = self.project_root()
        app_js = self.read_static_js("app.js")
        base_html = (project_root / "templates" / "base.html").read_text(encoding="utf-8")

        self.assertLessEqual(len(app_js.splitlines()), 80)
        self.assertIn("function initApp", app_js)
        self.assertIn("registerModalLifecycle();", app_js)
        self.assertIn("registerHtmxLifecycle();", app_js)
        self.assertIn("registerAppEventHandlers();", app_js)

        moved_functions = [
            "function storedValue",
            "function requestTmcProductSuggestions",
            "function markPreparingDownload",
            "function renderBulkPhotoFiles",
            "function uploadBulkPhotos",
            "function showToast",
            "function initTooltips",
            "function startPresenceHeartbeat",
            "function updateAdminFilterOrgBox",
            "function loadDepartment",
            "function syncRequestPhotoPicker",
            "function applyCollapsedPanels",
            "function registerHtmxLifecycle",
            "function registerAppEventHandlers",
        ]
        for function_name in moved_functions:
            with self.subTest(function=function_name):
                self.assertNotIn(function_name, app_js)

        for module_name in self.app_modules:
            with self.subTest(module=module_name):
                self.assertIn(f"js/{module_name}", base_html)

    def test_split_frontend_modules_contain_expected_responsibilities(self):
        expected_fragments = {
            "app_storage.js": ["function storedValue", "const ORGAN_STORAGE_KEY", "function formatLocalDateTime"],
            "app_dom_utils.js": ["function normalizeAuthInput", "function isVisibleElement"],
            "table_state.js": ["function tableUrlWithSavedState", "function resetTableStateToSingleOrgan"],
            "organ_navigation.js": ["function loadDepartment", "function setActiveOrgan", "function preferredDepartmentForOrgan"],
            "request_photo_picker.js": ["function syncRequestPhotoPicker", "function detachRequestPhoto", "function refreshCurrentTableArea"],
            "layout_panels.js": ["function syncHeaderHeight", "function applyCollapsedPanels"],
            "table_interactions.js": ["function filterCurrentTable", "function focusCurrentSearch", "function closeOpenModal"],
            "htmx_lifecycle.js": ["function registerHtmxLifecycle", "htmx:afterSwap", "bootstrap.Modal.getOrCreateInstance(document.getElementById(\"modal-root\")).show()", "modal:close", "function showToastFromHtmxTrigger", "requestPhotosChanged"],
            "app_events.js": ["function registerAppEventHandlers", "data-organ-mode", "data-request-photo-toggle"],
        }
        for module_name, fragments in expected_fragments.items():
            content = self.read_static_js(module_name)
            with self.subTest(module=module_name):
                for fragment in fragments:
                    self.assertIn(fragment, content)

    def test_frontend_modules_export_globals_used_by_app_js(self):
        for module_name, global_names in self.frontend_globals.items():
            module_js = self.read_static_js(module_name)
            with self.subTest(module=module_name):
                for global_name in global_names:
                    self.assertIn(f"window.{global_name}", module_js)

    def test_app_js_module_order_keeps_dependencies_before_bootstrap(self):
        project_root = self.project_root()
        base_html = (project_root / "templates" / "base.html").read_text(encoding="utf-8")

        script_order = [
            "js/custom_select.js",
            "js/photo_lightbox.js",
            "js/presence_ping.js",
            "js/admin_org_filter.js",
            "js/toasts.js",
            "js/confirm_dialog.js",
            "js/photo_upload.js",
            "js/tmc_products.js",
            "js/download_preparing.js",
            "js/app_storage.js",
            "js/app_dom_utils.js",
            "js/table_state.js",
            "js/organ_navigation.js",
            "js/request_photo_picker.js",
            "js/layout_panels.js",
            "js/table_interactions.js",
            "js/htmx_lifecycle.js",
            "js/app_events.js",
            "js/app.js",
        ]
        for previous, current in zip(script_order, script_order[1:]):
            with self.subTest(order=f"{previous} before {current}"):
                self.assertLess(base_html.index(previous), base_html.index(current))

    def test_confirm_dialog_replaces_native_browser_confirm(self):
        project_root = Path(__file__).resolve().parents[2]
        base_html = (project_root / "templates" / "base.html").read_text(encoding="utf-8")
        trash_template = (project_root / "templates" / "admin_panel" / "trash.html").read_text(encoding="utf-8")
        confirm_js = self.read_static_js("confirm_dialog.js")
        modals_css = (project_root / "static" / "css" / "app" / "modals-audit.css").read_text(encoding="utf-8")

        self.assertIn("js/confirm_dialog.js", base_html)
        self.assertLess(base_html.index("js/toasts.js"), base_html.index("js/confirm_dialog.js"))
        self.assertLess(base_html.index("js/confirm_dialog.js"), base_html.index("js/photo_upload.js"))
        self.assertNotIn('onsubmit="return confirm', trash_template)
        self.assertNotIn("confirm('", trash_template)
        self.assertIn("data-confirm-message", trash_template)
        self.assertIn('data-confirm-title="Безвозвратное удаление фотографии"', trash_template)
        self.assertIn('data-confirm-title="Безвозвратное удаление папки"', trash_template)
        self.assertIn("const ConfirmDialog", confirm_js)
        self.assertIn('document.addEventListener("submit", handleSubmit, true)', confirm_js)
        self.assertIn("app-confirm-dialog", confirm_js)
        self.assertIn("window.ConfirmDialog = ConfirmDialog", confirm_js)
        self.assertIn(".app-confirm-dialog", modals_css)
        self.assertIn(".app-confirm-details", modals_css)

    def test_floating_navigation_tooltip_can_align_left(self):
        project_root = Path(__file__).resolve().parents[2]
        dashboard_template = (project_root / "templates" / "dashboard" / "index.html").read_text(encoding="utf-8")
        base_css = (project_root / "static" / "css" / "app" / "base.css").read_text(encoding="utf-8")

        self.assertIn("navigation-float-toggle", dashboard_template)
        self.assertIn('data-tooltip-align="left"', dashboard_template)
        self.assertIn('[data-tooltip-align="left"][data-css-tooltip]::after', base_css)
        self.assertIn('[data-tooltip-align="left"][data-css-tooltip]::before', base_css)
        self.assertIn("left: 0", base_css)
        self.assertIn("left: 12px", base_css)
        self.assertIn("right: auto", base_css)
        self.assertIn("z-index: 2101", base_css)
        self.assertIn("width: 9px", base_css)
        self.assertIn("height: 9px", base_css)
        self.assertIn("transform: translateY(2px) rotate(45deg)", base_css)
        self.assertIn("transform: translateY(0) rotate(45deg)", base_css)

    def test_htmx_modal_lifecycle_dependencies_are_stable_after_module_split(self):
        htmx_js = self.read_static_js("htmx_lifecycle.js")
        toasts_js = self.read_static_js("toasts.js")

        self.assertIn('htmx:afterSwap', htmx_js)
        self.assertIn('bootstrap.Modal.getOrCreateInstance(document.getElementById("modal-root")).show()', htmx_js)
        self.assertIn('body.addEventListener("modal:close", closeModalFromHtmxTrigger)', htmx_js)
        self.assertIn('body.addEventListener("toast", showToastFromHtmxTrigger)', htmx_js)
        self.assertIn('body.addEventListener("requestPhotosChanged", refreshTableAfterRequestPhotosChanged)', htmx_js)
        self.assertIn('showToast(detail.message, detail.level || "success")', htmx_js)
        self.assertIn('refreshCurrentTableArea();', htmx_js)
        self.assertIn("initTooltips();", htmx_js)
        self.assertIn("window.initTooltips = initTooltips", toasts_js)


class AdminSearchOptimizationTests(TestCase):
    def project_root(self):
        return Path(__file__).resolve().parents[2]

    def test_admin_search_casefold_filtering_is_centralized(self):
        project_root = self.project_root()
        optimized_files = [
            project_root / "apps" / "accounts" / "admin_asset_services.py",
            project_root / "apps" / "accounts" / "admin_assets.py",
            project_root / "apps" / "accounts" / "admin_organs.py",
            project_root / "apps" / "accounts" / "admin_departments.py",
        ]
        for path in optimized_files:
            content = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn(".casefold()", content)
                self.assertNotIn("casefold(", content)

        common = (project_root / "apps" / "accounts" / "admin_common.py").read_text(encoding="utf-8")
        self.assertIn("def filter_model_objects_by_search", common)
        self.assertIn("def filter_department_options_by_search", common)
        self.assertIn("pk__in=pks", common)
        self.assertIn('values_list("pk", flat=True)', common)

    def test_admin_search_modules_use_orm_search_helpers(self):
        project_root = self.project_root()
        expectations = {
            "admin_asset_services.py": "filter_model_objects_by_search",
            "admin_organs.py": "filter_model_objects_by_search",
            "admin_departments.py": "filter_department_options_by_search",
        }
        for filename, helper in expectations.items():
            content = (project_root / "apps" / "accounts" / filename).read_text(encoding="utf-8")
            with self.subTest(file=filename):
                self.assertIn(helper, content)

    def test_admin_employee_and_asset_panels_are_split_into_service_modules(self):
        project_root = self.project_root()
        expected_modules = [
            "admin_employee_core.py",
            "admin_employee_forms.py",
            "admin_employee_actions.py",
            "admin_asset_services.py",
        ]
        for filename in expected_modules:
            with self.subTest(file=filename):
                self.assertTrue((project_root / "apps" / "accounts" / filename).exists())

        employees_panel = (project_root / "apps" / "accounts" / "admin_employees.py").read_text(encoding="utf-8")
        assets_panel = (project_root / "apps" / "accounts" / "admin_assets.py").read_text(encoding="utf-8")
        self.assertIn("from .admin_employee_core import", employees_panel)
        self.assertIn("from .admin_employee_actions import", employees_panel)
        self.assertIn("from .admin_asset_services import", assets_panel)


class AdminTrashPanelTests(AdminPanelTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

    def uploaded_image(self, filename="trash.png"):
        buffer = tempfile.SpooledTemporaryFile()
        Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
        buffer.seek(0)
        return SimpleUploadedFile(filename, buffer.read(), content_type="image/png")

    def test_trash_panel_is_available_to_admin(self):
        self.login_admin()

        response = self.client.get(reverse("admin_trash_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "trash")
        self.assertContains(response, "Корзина удаленных объектов")
        self.assertContains(response, "admin-top-tab admin-top-tab-separated active")

    def test_trash_tab_has_separate_right_alignment_and_card_spacing_styles(self):
        project_root = Path(__file__).resolve().parents[2]
        base_css = (project_root / "static" / "css" / "admin" / "base.css").read_text(encoding="utf-8")
        trash_css = (project_root / "static" / "css" / "admin" / "trash.css").read_text(encoding="utf-8")

        self.assertIn(".admin-top-tab-separated", base_css)
        self.assertIn("margin-left: auto", base_css)
        self.assertIn(".admin-trash-screen", trash_css)
        self.assertIn("display: grid", trash_css)
        self.assertIn("gap: 12px", trash_css)
        self.assertIn(".admin-trash-filter-row", trash_css)
        self.assertIn("display: flex", trash_css)
        self.assertIn("flex: 1 1 320px", trash_css)
        self.assertIn(".admin-trash-filter-actions", trash_css)
        self.assertIn("flex: 0 0 auto", trash_css)
        self.assertIn(".admin-trash-action-cell", trash_css)
        self.assertIn("vertical-align: middle", trash_css)
        self.assertIn("justify-content: center", trash_css)
        self.assertIn(".admin-trash-folder-node", trash_css)
        self.assertIn(".admin-trash-folder-child-list", trash_css)
        self.assertIn("margin-left: calc(var(--tree-depth, 0) * 18px)", trash_css)

    def test_admin_tables_have_centered_headers_and_smooth_hover(self):
        project_root = Path(__file__).resolve().parents[2]
        requests_css = (project_root / "static" / "css" / "admin" / "requests.css").read_text(encoding="utf-8")
        admin_css = (project_root / "static" / "css" / "admin.css").read_text(encoding="utf-8")
        trash_template = (project_root / "templates" / "admin_panel" / "trash.html").read_text(encoding="utf-8")

        self.assertIn(".admin-requests-table thead th", requests_css)
        self.assertIn("text-align: center", requests_css)
        self.assertIn("transition: background-color .14s var(--motion-smooth), border-color .14s var(--motion-smooth)", requests_css)
        self.assertIn(".admin-requests-table td:last-child", requests_css)
        self.assertIn("justify-content: center", requests_css)
        self.assertIn("admin/base.css?v=20260707-001", admin_css)
        self.assertIn("admin/requests.css?v=20260707-001", admin_css)
        self.assertIn("admin/trash.css?v=20260705-016", admin_css)
        self.assertIn("css/admin.css' %}?v=20260707-002", trash_template)



    def test_admin_open_buttons_do_not_use_eye_icons(self):
        project_root = Path(__file__).resolve().parents[2]
        template_root = project_root / "templates" / "admin_panel"
        offenders = []
        for template_path in template_root.rglob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            if '<i class="bi bi-eye"></i>' in content and "Открыть" in content:
                compact = " ".join(content.split())
                if 'bi bi-eye"></i> Открыть' in compact:
                    offenders.append(str(template_path.relative_to(project_root)))
        self.assertEqual(offenders, [])

    def test_trash_request_rows_have_open_button_and_deleted_detail_view(self):
        self.login_admin()
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            updated_by=self.admin,
            request_number="ТМЦ-OPEN",
            request_date=timezone.localdate(),
            comment="Удалённая запись для просмотра",
            is_deleted=True,
        )

        response = self.client.get(reverse("admin_trash_panel") + "?section=requests")

        self.assertEqual(response.status_code, 200)
        detail_url = reverse("admin_request_detail", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}) + "?deleted=1"
        self.assertContains(response, f'href="{detail_url}"')
        self.assertContains(response, "Открыть")
        self.assertContains(response, "admin-trash-action-cell")

        detail_response = self.client.get(detail_url)

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context["active_tab"], "trash")
        self.assertTrue(detail_response.context["is_deleted_detail"])
        self.assertContains(detail_response, "Эта запись находится в корзине")
        self.assertContains(detail_response, "Назад в корзину")
        self.assertNotContains(detail_response, "Назад к реестру")
        self.assertContains(detail_response, "Удалённая запись для просмотра")

    def test_trash_request_rows_show_department_display_name(self):
        self.login_admin()
        self.department_transport.name = "Автотранспортное хозяйство"
        self.department_transport.save(update_fields=["name"])
        VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            updated_by=self.admin,
            request_number="АТХ-404",
            request_date=timezone.localdate(),
            is_deleted=True,
        )

        response = self.client.get(reverse("admin_trash_panel") + "?section=requests")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Автотранспортное хозяйство")
        self.assertNotContains(response, ">transport</span>")

    def test_trash_photo_rows_show_lightbox_thumbnail(self):
        self.login_admin()
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Акты", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Проверка", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            folder=child,
            image=self.uploaded_image("trash-preview.png"),
            description="Фото для предпросмотра",
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )

        response = self.client.get(reverse("admin_trash_panel") + "?section=photos")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-trash-photo-thumb")
        self.assertContains(response, "data-lightbox-photo")
        self.assertContains(response, photo.image.url)
        self.assertContains(response, "Фото для предпросмотра")
        self.assertContains(response, "Акты / Проверка")
        self.assertNotContains(response, ">Корень / Акты / Проверка<")

    def test_trash_folder_rows_show_mini_browser_with_deleted_photos(self):
        self.login_admin()
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Удалённый объект", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Вложенный акт", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        grandchild = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=child, name="Глубокая папка", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            folder=grandchild,
            image=self.uploaded_image("nested-preview.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )

        response = self.client.get(reverse("admin_trash_panel") + "?section=folders")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["folder_page"].paginator.count, 1)
        self.assertContains(response, "admin-trash-folder-node")
        self.assertContains(response, "admin-trash-folder-child-list")
        self.assertContains(response, "Вложенный акт")
        self.assertContains(response, "Глубокая папка")
        self.assertContains(response, 'style="--tree-depth: 1;"')
        self.assertContains(response, 'style="--tree-depth: 2;"')
        self.assertContains(response, "Фотографии в этой папке")
        self.assertNotContains(response, "Фотографии в дереве папки")
        self.assertContains(response, f'data-lightbox-group="trash-folder-{grandchild.pk}"')
        self.assertContains(response, photo.image.url)
        self.assertContains(response, "nested-preview.png")
        self.assertContains(response, "Удалить папку")
        self.assertNotContains(response, ">Очистить</button>")


    def test_trash_restore_child_folder_warning_uses_visible_alert(self):
        self.login_admin()
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Родитель", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Подпапка", created_by=self.admin, updated_by=self.admin, is_deleted=True)

        response = self.client.post(reverse("admin_trash_restore_folder", kwargs={"pk": child.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alert-danger")
        self.assertContains(response, "Нельзя восстановить папку: сначала восстановите родительскую папку.")

    def test_trash_restores_deleted_request_and_registry_number(self):
        self.login_admin()
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            updated_by=self.admin,
            request_number="ТМЦ-777",
            request_date=timezone.localdate(),
            is_deleted=True,
        )
        self.assertFalse(RequestNumberRegistry.objects.exists())

        response = self.client.post(reverse("admin_trash_restore_request", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}))

        self.assertEqual(response.status_code, 302)
        request_obj.refresh_from_db()
        self.assertFalse(request_obj.is_deleted)
        self.assertTrue(RequestNumberRegistry.objects.filter(object_id=request_obj.pk, request_number="ТМЦ-777").exists())
        self.assertTrue(AuditLog.objects.filter(model_name="TmcRequest", object_id=str(request_obj.pk), new_values__audit_event="request_restored_from_trash").exists())

    def test_trash_restores_deleted_photo(self):
        self.login_admin()
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            image=self.uploaded_image("restore.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )

        response = self.client.post(reverse("admin_trash_restore_photo", kwargs={"pk": photo.pk}))

        self.assertEqual(response.status_code, 302)
        photo.refresh_from_db()
        self.assertFalse(photo.is_deleted)
        self.assertTrue(AuditLog.objects.filter(model_name="TerritorialOrganPhoto", object_id=str(photo.pk), new_values__audit_event="photo_restored_from_trash").exists())

    def test_trash_permanently_deletes_soft_deleted_photo_file_for_leader(self):
        self.login_admin()
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            image=self.uploaded_image("purge.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )
        file_path = Path(photo.image.path)
        self.assertTrue(file_path.exists())
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="ТМЦ-778",
            request_date=timezone.localdate(),
        )
        RequestPhotoLink.objects.create(territorial_organ=self.organ, photo=photo, request=request_obj, created_by=self.admin)

        response = self.client.post(reverse("admin_trash_purge_photo", kwargs={"pk": photo.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TerritorialOrganPhoto.objects.filter(pk=photo.pk).exists())
        self.assertFalse(file_path.exists())
        self.assertFalse(RequestPhotoLink.objects.filter(photo_id=photo.pk).exists())
        self.assertTrue(AuditLog.objects.filter(model_name="TerritorialOrganPhoto", object_id=str(photo.pk), new_values__audit_event="photo_file_permanently_deleted").exists())

    def test_profile_admin_cannot_permanently_delete_photo_file(self):
        profile_admin = self.User.objects.create_user("profile_admin", password="pass12345", is_staff=False)
        UserProfile.objects.create(user=profile_admin, role=UserProfile.Role.ADMIN)
        self.client.login(username="profile_admin", password="pass12345")
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            image=self.uploaded_image("forbidden.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )

        response = self.client.post(reverse("admin_trash_purge_photo", kwargs={"pk": photo.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(TerritorialOrganPhoto.objects.filter(pk=photo.pk).exists())

    def test_trash_restores_deleted_folder_tree_with_photos(self):
        self.login_admin()
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Удалённая папка", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Вложенная", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            folder=child,
            image=self.uploaded_image("nested.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )

        response = self.client.post(reverse("admin_trash_restore_folder", kwargs={"pk": folder.pk}))

        self.assertEqual(response.status_code, 302)
        folder.refresh_from_db()
        child.refresh_from_db()
        photo.refresh_from_db()
        self.assertFalse(folder.is_deleted)
        self.assertFalse(child.is_deleted)
        self.assertFalse(photo.is_deleted)
        self.assertTrue(AuditLog.objects.filter(model_name="TerritorialOrganPhotoFolder", object_id=str(folder.pk), new_values__audit_event="photo_folder_tree_restored_from_trash").exists())

    def test_trash_permanently_deletes_deleted_folder_tree_and_files_for_leader(self):
        self.login_admin()
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Очистить", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            folder=folder,
            image=self.uploaded_image("folder-purge.png"),
            created_by=self.admin,
            updated_by=self.admin,
            is_deleted=True,
        )
        file_path = Path(photo.image.path)
        self.assertTrue(file_path.exists())

        response = self.client.post(reverse("admin_trash_purge_folder", kwargs={"pk": folder.pk}))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TerritorialOrganPhotoFolder.objects.filter(pk=folder.pk).exists())
        self.assertFalse(TerritorialOrganPhoto.objects.filter(pk=photo.pk).exists())
        self.assertFalse(file_path.exists())
        self.assertTrue(AuditLog.objects.filter(model_name="TerritorialOrganPhotoFolder", object_id=str(folder.pk), new_values__audit_event="photo_folder_tree_permanently_deleted").exists())
