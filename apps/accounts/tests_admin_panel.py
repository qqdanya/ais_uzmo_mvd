import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import FireExtinguisher, NeedStatus, TmcRequest, VehicleRepairRequest

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

    def test_employees_panel_department_filter_includes_unrestricted_department_access(self):
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
        self.assertIn("all_depts", usernames)
        self.assertNotIn("transport_only", usernames)
        self.assertIn("Отделы: ТМЦ", response.context["active_filter_chips"])

    def test_employee_empty_department_permissions_are_displayed_as_full_department_access(self):
        self.login_admin()
        target = self.User.objects.create_user("all_department_access", first_name="Артём", last_name="Полный")
        profile = UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)
        profile.allowed_organs.set([self.organ])

        response = self.client.get(reverse("admin_employee_detail", kwargs={"pk": target.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["departments_summary"], "Все отделы")
        self.assertTrue(response.context["all_departments"])
        self.assertFalse(response.context["no_departments"])
        self.assertContains(response, "Все отделы")

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
        self.assertIn("Состояния: Проблемные", response.context["active_filter_chips"])
        self.assertIn("Поиск: Другой", response.context["active_filter_chips"])

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

