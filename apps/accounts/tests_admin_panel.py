import json
import shutil
import tempfile
from io import BytesIO
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import FireExtinguisher, NeedStatus, RequestNumberRegistry, RequestPhotoLink, RequestStatusHistory, TmcRequest, VehicleRepairRequest

from .admin_asset_services import latest_objects_by_organ
from .admin_thresholds import _THRESHOLDS_CACHE, get_dashboard_thresholds
from .models import UserProfile


class AdminPanelTestMixin:
    def setUp(self):
        # admin_summary_data caches by user pk + query params (see
        # summary_data_cache_key); Django's cache isn't reset between test
        # methods on its own, and transactional test PKs can repeat, so a
        # stale hit from an earlier test could otherwise leak into this one.
        cache.clear()
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

    def test_admin_panel_shell_skips_summary_aggregates_and_leaves_them_to_summary_data(self):
        today = timezone.localdate()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="1",
            request_date=today,
        )
        self.login_admin()

        response = self.client.get(reverse("admin_panel"))

        self.assertEqual(response.status_code, 200)
        # The heavy build_summary_payload() aggregates (kpi/dynamics/org_chart/
        # department_load/attention_requests) must not run on this synchronous
        # request — admin_summary.js fetches them from admin_summary_data right
        # after the shell paints. The organ list is still needed for the
        # selector, so that one stays populated.
        self.assertEqual(response.context["summary_payload"], {})
        self.assertIn(self.organ, response.context["organs"])
        self.assertContains(response, "data-admin-summary-root")
        self.assertContains(response, reverse("admin_summary_data"))
        self.assertContains(response, "data-admin-calendar-jump-toggle")
        self.assertContains(response, "data-admin-calendar-month-picker")
        self.assertLess(response.content.index("previous_month".encode()), response.content.index("today".encode()))

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

    def test_summary_data_is_cached_per_user_and_params(self):
        self.login_admin()
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="cache-1",
            request_date=timezone.localdate(),
            status=NeedStatus.IN_WORK,
        )

        first = self.client.get(reverse("admin_summary_data")).json()
        self.assertEqual(first["kpi"]["total"], 1)

        # A second request with the same params must hit the cache and keep
        # returning the stale total, not recompute from the DB.
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            request_number="cache-2",
            request_date=timezone.localdate(),
            status=NeedStatus.IN_WORK,
        )
        cached = self.client.get(reverse("admin_summary_data")).json()
        self.assertEqual(cached["kpi"]["total"], 1)

        # Different params (a different cache key) must not reuse that
        # stale entry - it should compute fresh and see both requests.
        different_params = self.client.get(reverse("admin_summary_data"), {"org_metric": "done"}).json()
        self.assertEqual(different_params["kpi"]["total"], 2)

        # Once the cache entry is gone (TTL expiry in production; cleared
        # here to avoid a real 45s sleep), the same params compute fresh.
        cache.clear()
        refreshed = self.client.get(reverse("admin_summary_data")).json()
        self.assertEqual(refreshed["kpi"]["total"], 2)

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
        self.assertNotContains(profile_admin_response, "Управление данными")
        self.assertNotContains(profile_admin_response, f'href="{reverse("admin:index")}"')

        self.client.logout()
        self.login_admin()
        leader_response = self.client.get(reverse("admin_panel"))
        self.assertContains(leader_response, "Управление данными")
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
        # The photo is served through the permission-checked preview endpoint,
        # not a raw /media/... URL that would bypass the per-organ access check.
        self.assertContains(response, reverse("photo_preview", args=[self.organ.pk, photo.pk]))

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

    def create_done_request_needing_history_lookup(self, number):
        # No completed_at/due_date on the object itself, so processing_days()
        # can only resolve the completion date via RequestStatusHistory -
        # exactly the case attach_processing_end_dates() is meant to batch.
        obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.admin,
            updated_by=self.admin,
            request_number=number,
            request_date=timezone.localdate(),
            status=NeedStatus.DONE,
        )
        RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(TmcRequest, for_concrete_model=False),
            object_id=obj.pk,
            old_status=NeedStatus.IN_WORK,
            new_status=NeedStatus.DONE,
            changed_by=self.admin,
        )
        return obj

    def history_query_count(self, queries_context):
        # Isolates the metric the fix actually targets from unrelated noise
        # (session-save UPDATEs, SAVEPOINTs) that varies run-to-run for
        # reasons that have nothing to do with attach_processing_end_dates().
        return sum(1 for q in queries_context.captured_queries if "requeststatushistory" in q["sql"].lower())

    def test_organ_detail_latest_requests_avoid_n_plus_one_on_processing_days(self):
        self.login_admin()
        for index in range(2):
            self.create_done_request_needing_history_lookup(f"organ-np1-{index}")
        with CaptureQueriesContext(connection) as few_queries:
            self.client.get(reverse("admin_organ_detail", kwargs={"pk": self.organ.pk}))

        for index in range(2, 12):
            self.create_done_request_needing_history_lookup(f"organ-np1-{index}")
        with CaptureQueriesContext(connection) as many_queries:
            self.client.get(reverse("admin_organ_detail", kwargs={"pk": self.organ.pk}))

        # If processing_days() were falling back to a per-row history query,
        # this would scale with row count (2 vs 12 done requests); with
        # attach_processing_end_dates() batching it up front, it doesn't.
        self.assertEqual(self.history_query_count(few_queries), self.history_query_count(many_queries))

    def test_department_detail_latest_requests_avoid_n_plus_one_on_processing_days(self):
        self.login_admin()
        for index in range(2):
            self.create_done_request_needing_history_lookup(f"dept-np1-{index}")
        with CaptureQueriesContext(connection) as few_queries:
            self.client.get(reverse("admin_department_detail", kwargs={"department_slug": "tmc"}))

        for index in range(2, 12):
            self.create_done_request_needing_history_lookup(f"dept-np1-{index}")
        with CaptureQueriesContext(connection) as many_queries:
            self.client.get(reverse("admin_department_detail", kwargs={"department_slug": "tmc"}))

        self.assertEqual(self.history_query_count(few_queries), self.history_query_count(many_queries))


class AdminEmployeesPanelTests(AdminPanelTestMixin, TestCase):
    def test_employees_panel_search_is_case_insensitive_for_cyrillic(self):
        self.login_admin()
        target = self.User.objects.create_user("case_user", first_name="Марина", last_name="Соколова")
        profile = UserProfile.objects.create(user=target, role=UserProfile.Role.OPERATOR)
        profile.allowed_organs.set([self.organ])
        profile.allowed_departments.set([self.department_tmc])

        response = self.client.get(reverse("admin_employees_panel"), {"q": "соколова"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "case_user")

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

    def test_asset_organ_detail_history_is_bounded(self):
        # Regression test: build_asset_organ_detail_context used to load the
        # entire state-snapshot history for an organ/category with no limit
        # or pagination - years of periodic submissions could return
        # hundreds of rows onto one unpaginated page.
        self.login_admin()
        today = timezone.localdate()
        for index in range(60):
            FireExtinguisher.objects.create(
                territorial_organ=self.organ,
                created_by=self.admin,
                state_date=today - timezone.timedelta(days=index),
                required_count=10,
                available_count=10,
                expiry_date=today + timezone.timedelta(days=365),
                writeoff_count=0,
            )

        response = self.client.get(reverse("admin_asset_organ_detail", kwargs={"category_key": "fire-extinguishers", "organ_id": self.organ.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.context["history_rows"]), 50)

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

    def test_latest_objects_by_organ_picks_newest_row_per_organ_by_tiebreak_order(self):
        today = timezone.localdate()
        now = timezone.now()

        def make(state_date, created_at, **fields):
            obj = FireExtinguisher.objects.create(
                territorial_organ=self.organ,
                created_by=self.admin,
                state_date=state_date,
                expiry_date=today + timezone.timedelta(days=365),
                writeoff_count=0,
                **fields,
            )
            FireExtinguisher.objects.filter(pk=obj.pk).update(created_at=created_at)
            return obj

        make(today - timezone.timedelta(days=10), now - timezone.timedelta(days=20), required_count=10, available_count=10)
        # Same state_date as `newest`, but an earlier created_at: created_at is
        # the tiebreak, so this row must lose to `newest`, not be picked instead.
        make(today, now - timezone.timedelta(hours=2), required_count=5, available_count=5)
        newest = make(today, now - timezone.timedelta(hours=1), required_count=8, available_count=8)

        latest = latest_objects_by_organ({"model": FireExtinguisher}, [self.organ, self.other_organ])

        self.assertEqual(set(latest.keys()), {self.organ.pk})
        self.assertEqual(latest[self.organ.pk].pk, newest.pk)
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

    # Core: needed on every page, so they stay directly in base.html.
    app_modules = [
        "app_storage.js",
        "app_dom_utils.js",
        "auth_ui.js",
        "layout_panels.js",
        "htmx_lifecycle.js",
        "app.js",
    ]

    # Dashboard-only: no unconditional caller outside the dashboard shell, so
    # they're loaded via partials/scripts/dashboard_scripts.html instead.
    # organ_navigation.js/table_interactions.js/app_events.js used to be core
    # because app.js and photo_lightbox.js called into them unconditionally;
    # closeOpenModal/focusCurrentSearch/scrollAfterPaginationSwap moved to
    # htmx_lifecycle.js, the auth-only bits of app_events.js moved to
    # auth_ui.js, and initApp() now guards the rest behind a
    # typeof applyDashboardUrlState check, so what's left of these three is
    # genuinely dashboard-only.
    dashboard_only_modules = [
        "organ_navigation.js",
        "table_interactions.js",
        "app_events.js",
        "table_state.js",
        "request_photo_picker.js",
    ]

    # Admin-panel-only: same reasoning, loaded via partials/scripts/admin_scripts.html.
    admin_only_modules = [
        "confirm_dialog.js",
        "admin_multiselect.js",
        "employees_presence.js",
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
        for module_name in self.dashboard_only_modules + self.admin_only_modules:
            with self.subTest(module=module_name):
                self.assertNotIn(f"js/{module_name}", base_html)

        dashboard_scripts = (project_root / "templates" / "partials" / "scripts" / "dashboard_scripts.html").read_text(encoding="utf-8")
        for module_name in self.dashboard_only_modules:
            with self.subTest(module=module_name):
                self.assertIn(f"js/{module_name}", dashboard_scripts)

        admin_scripts = (project_root / "templates" / "partials" / "scripts" / "admin_scripts.html").read_text(encoding="utf-8")
        for module_name in self.admin_only_modules:
            with self.subTest(module=module_name):
                self.assertIn(f"js/{module_name}", admin_scripts)

        # admin_org_filter.js is needed by both the dashboard table toolbar and
        # admin_panel filter forms, so it lives in both bundles, not base.html.
        self.assertNotIn("js/admin_org_filter.js", base_html)
        self.assertIn("js/admin_org_filter.js", dashboard_scripts)
        self.assertIn("js/admin_org_filter.js", admin_scripts)

    def test_split_frontend_modules_contain_expected_responsibilities(self):
        expected_fragments = {
            "app_storage.js": ["function storedValue", "const ORGAN_STORAGE_KEY", "function formatLocalDateTime"],
            "app_dom_utils.js": ["function normalizeAuthInput", "function isVisibleElement"],
            "table_state.js": ["function tableUrlWithSavedState", "function resetTableStateToSingleOrgan"],
            "organ_navigation.js": ["function loadDepartment", "function setActiveOrgan", "function preferredDepartmentForOrgan"],
            "request_photo_picker.js": ["function syncRequestPhotoPicker", "function detachRequestPhoto", "function refreshCurrentTableArea"],
            "layout_panels.js": ["function syncHeaderHeight", "function applyCollapsedPanels"],
            "table_interactions.js": ["function filterCurrentTable", "function setTableGroupHover", "function fillCompletedDate"],
            "htmx_lifecycle.js": ["function registerHtmxLifecycle", "htmx:afterSwap", "bootstrap.Modal.getOrCreateInstance(document.getElementById(\"modal-root\")).show()", "modal:close", "function showToastFromHtmxTrigger", "requestPhotosChanged", "function focusCurrentSearch", "function closeOpenModal", "function scrollAfterPaginationSwap"],
            "app_events.js": ["function registerAppEventHandlers", "data-organ-mode", "data-request-photo-toggle"],
            "auth_ui.js": ["auth-ascii-input", "data-password-toggle"],
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
            "js/toasts.js",
            "js/tmc_products.js",
            "js/app_storage.js",
            "js/app_dom_utils.js",
            "js/auth_ui.js",
            "js/layout_panels.js",
            "js/htmx_lifecycle.js",
            "js/app.js",
        ]
        for previous, current in zip(script_order, script_order[1:]):
            with self.subTest(order=f"{previous} before {current}"):
                self.assertLess(base_html.index(previous), base_html.index(current))

    def test_confirm_dialog_replaces_native_browser_confirm(self):
        project_root = Path(__file__).resolve().parents[2]
        admin_scripts = (project_root / "templates" / "partials" / "scripts" / "admin_scripts.html").read_text(encoding="utf-8")
        trash_template = (project_root / "templates" / "admin_panel" / "trash.html").read_text(encoding="utf-8")
        confirm_js = self.read_static_js("confirm_dialog.js")
        modals_css = (project_root / "static" / "css" / "app" / "modals-audit.css").read_text(encoding="utf-8")

        # confirm_dialog.js is only used by admin_panel pages (see FrontendModuleSplitTests
        # above), so it's loaded via the admin_scripts.html bundle, not base.html directly.
        self.assertIn("js/confirm_dialog.js", admin_scripts)
        self.assertIn('{% include "partials/scripts/admin_scripts.html" %}', trash_template)
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

    def test_floating_navigation_tooltip_shows_to_the_right(self):
        project_root = Path(__file__).resolve().parents[2]
        dashboard_template = (project_root / "templates" / "dashboard" / "index.html").read_text(encoding="utf-8")
        toasts_js = self.read_static_js("toasts.js")

        # .navigation-float-toggle sits pinned to the left screen edge and
        # the top of the panel, so its tooltip can't go above (clips the
        # panel top) or to the left (clips the viewport edge) - it needs to
        # go right, vertically centered, driven by the class alone so the
        # template doesn't need a placement attribute on this button.
        self.assertIn("navigation-float-toggle", dashboard_template)
        self.assertNotIn("data-tooltip-align", dashboard_template)
        self.assertIn('trigger.classList.contains("navigation-float-toggle")', toasts_js)
        self.assertIn('return ["right", "bottom", "top", "left"];', toasts_js)

    def test_table_action_stack_tooltip_shows_to_the_left(self):
        toasts_js = self.read_static_js("toasts.js")

        # .table-action-stack stacks its row-action icons vertically, so a
        # tooltip above/below one icon would cover the icon next to it -
        # driven by the container class alone, no per-button attribute.
        self.assertIn('trigger.closest(".table-action-stack")', toasts_js)
        self.assertIn('return ["left", "right", "top", "bottom"];', toasts_js)

    def test_tooltips_render_as_a_body_level_portal(self):
        base_css = (self.project_root() / "static" / "css" / "app" / "base.css").read_text(encoding="utf-8")
        toasts_js = self.read_static_js("toasts.js")

        # Tooltips used to be ::before/::after pseudo-elements positioned
        # absolute on the trigger, which .organ-panel/.department-panel
        # clipped (overflow-x: hidden forces overflow-y: visible to compute
        # as auto per the CSS Overflow spec, so both axes clip regardless of
        # z-index). Rendering a single element straight on <body>, positioned
        # fixed and recomputed from getBoundingClientRect(), escapes any
        # ancestor's overflow instead of fighting it.
        self.assertIn(".app-tooltip-portal {", base_css)
        self.assertIn("position: fixed;", base_css)
        self.assertIn('portal = document.createElement("div")', toasts_js)
        self.assertIn('document.body.append(portal)', toasts_js)
        self.assertIn("function positionTooltip", toasts_js)
        self.assertIn('window.addEventListener("resize", scheduleTooltipPosition)', toasts_js)
        self.assertIn('document.addEventListener("scroll", scheduleTooltipPosition, true)', toasts_js)

        # The arrow is drawn as a single ::after triangle that never overlaps
        # the bubble - two overlapping semi-transparent layers previously
        # alpha-composited into a visibly darker seam than the rest of the
        # tooltip.
        self.assertIn(".app-tooltip-portal::after {", base_css)
        self.assertNotIn("rotate(45deg)", base_css)

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

    def test_app_js_skips_redundant_fetch_only_when_state_matches_server_default(self):
        # A returning visitor whose saved organ/department/table happen to
        # match dashboard_context()'s server-rendered default must skip the
        # #organ-info/#workspace re-fetch too, not just a visitor with
        # nothing saved at all — checking "is anything saved" alone would
        # still re-fetch for the (common) case of a saved preference that
        # matches the default.
        app_js = self.read_static_js("app.js")
        organ_navigation_js = self.read_static_js("organ_navigation.js")

        self.assertIn("function serverRenderedWorkspaceState", organ_navigation_js)
        self.assertIn("serverRenderedWorkspaceState()", app_js)
        self.assertIn("const tableKey = savedTableKeyForDepartment(department.dataset.departmentSlug)", app_js)
        self.assertIn("serverDefault.organId === String(window.selectedOrgan)", app_js)
        self.assertIn("serverDefault.departmentSlug === department.dataset.departmentSlug", app_js)
        self.assertIn("serverDefault.tableKey === tableKey", app_js)

    def test_htmx_lifecycle_guards_dashboard_only_calls_for_pages_without_them(self):
        # htmx_lifecycle.js is core (loads on every page, e.g. audit_log.html's
        # own hx-get modal button), but syncRequestPhotoPicker/
        # syncActiveDownloadButtons/saveTableStateFromHtmxEvent/
        # isResetTableStateTrigger/refreshCurrentTableArea only exist on the
        # dashboard bundle. An unconditional reference — even just passing
        # the bare name to forEach() — throws a ReferenceError the moment any
        # htmx swap or request fires on a page without that module loaded.
        htmx_js = self.read_static_js("htmx_lifecycle.js")

        self.assertIn('typeof syncRequestPhotoPicker === "function"', htmx_js)
        self.assertIn('typeof syncActiveDownloadButtons === "function"', htmx_js)
        self.assertIn('typeof saveTableStateFromHtmxEvent === "function"', htmx_js)
        self.assertIn('typeof isResetTableStateTrigger !== "function"', htmx_js)
        self.assertIn('typeof refreshCurrentTableArea === "function"', htmx_js)
        self.assertIn("bulkForm && window.PhotoUpload", htmx_js)

    def test_dashboard_skip_respects_saved_table_search_and_filters(self):
        # matchesServerDefault must not skip loadDepartment() just because
        # organ/department/table match the SSR default — the SSR render never
        # applies a saved search/filter/page for that table, so a saved query
        # still means the plain default view isn't what should be shown.
        app_js = self.read_static_js("app.js")

        self.assertIn("savedTableQuery(department.dataset.departmentSlug, tableKey)", app_js)
        match_block = app_js[app_js.index("const matchesServerDefault"):app_js.index("if (!matchesServerDefault)")]
        self.assertIn("!savedTableQuery", match_block)

    def test_photo_lightbox_close_releases_item_list_and_view_state(self):
        # photoLightboxState.items holds { trigger: <button> } for every photo
        # in the group (not just the one shown), and lastTrigger/scale/offset
        # are per-session state too — none of it should outlive a close, or
        # DOM nodes from a table/modal an HTMX swap has since replaced stay
        # reachable, and the next photo opened could inherit stale zoom/pan.
        lightbox_js = self.read_static_js("photo_lightbox.js")
        close_fn_start = lightbox_js.index("function closePhotoLightbox")
        close_fn_body = lightbox_js[close_fn_start:lightbox_js.index("\nfunction ", close_fn_start + 1)]

        self.assertIn("photoLightboxState.lastTrigger = null;", close_fn_body)
        self.assertIn("photoLightboxState.items = [];", close_fn_body)
        self.assertIn("photoLightboxState.index = 0;", close_fn_body)
        self.assertIn("photoLightboxState.didDrag = false;", close_fn_body)
        self.assertIn("resetLightboxView();", close_fn_body)
        self.assertIn('image.removeAttribute("src");', close_fn_body)


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


class PerformanceRegressionTests(AdminPanelTestMixin, TestCase):
    """Query-count ceilings for /control/requests/ and /control/summary-data/.

    Not meant to force an exact "ideal" count - just to catch a future N+1
    before it ships. Bounds are set with headroom over the count measured at
    the time the test was written (noted per test).
    """

    def seed_tmc_requests(self, count=10):
        for index in range(count):
            TmcRequest.objects.create(
                territorial_organ=self.organ,
                created_by=self.admin,
                request_number=f"perf-{index}",
                request_date=timezone.localdate(),
                status=NeedStatus.IN_WORK,
            )

    def test_admin_requests_panel_query_count_has_a_ceiling(self):
        # Measured 38 queries for 10 seeded requests at write time - this
        # page scans every request table (not just tmc-requests) to build
        # the combined registry view.
        self.seed_tmc_requests()
        self.login_admin()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("admin_requests_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 50)

    def test_admin_summary_data_query_count_has_a_ceiling(self):
        # Measured 78 queries for 10 seeded requests after consolidating the
        # total/in-work/stale/department-load scans into one aggregate per
        # request table. This
        # endpoint aggregates KPI/dynamics/org-chart/department-load/attention
        # across every request table, so it's naturally the heaviest page
        # in the app (already reduced from 139 in an earlier optimization
        # pass - see admin_panel N+1 fix history).
        self.seed_tmc_requests()
        self.login_admin()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("admin_summary_data"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 100)


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

    def test_trash_panel_is_available_to_operator_without_admin_navigation(self):
        self.login_operator()

        response = self.client.get(reverse("trash_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Корзина удаленных объектов")
        self.assertNotContains(response, "Административная панель")
        self.assertNotContains(response, "admin-top-tabs")
        self.assertEqual(reverse("trash_panel"), "/trash/")
        self.assertEqual(reverse("admin_trash_panel"), "/control/trash/")
        self.assertEqual(self.client.get(reverse("admin_trash_panel")).status_code, 403)

    def test_admin_personal_trash_has_no_admin_navigation(self):
        self.login_admin()

        response = self.client.get(reverse("trash_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_personal_trash"])
        self.assertNotContains(response, "admin-top-tabs")

    def test_authenticated_operator_menu_contains_trash_link(self):
        self.login_operator()

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("trash_panel"))
        self.assertContains(response, '<i class="bi bi-trash3"></i> Корзина', html=False)

    def test_operator_personal_trash_can_hide_item_without_removing_it_from_admin_trash(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.operator,
            updated_by=self.operator,
            request_number="ТМЦ-PERSONAL",
            request_date=timezone.localdate(),
            is_deleted=True,
        )
        self.login_operator()

        personal_response = self.client.get(reverse("trash_panel") + "?section=requests")
        self.assertContains(personal_response, "ТМЦ-PERSONAL")
        self.assertContains(personal_response, reverse("trash_dismiss_request", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}))

        dismiss_response = self.client.post(reverse("trash_dismiss_request", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}), follow=True)
        self.assertEqual(dismiss_response.status_code, 200)
        self.assertNotContains(dismiss_response, "ТМЦ-PERSONAL")
        request_obj.refresh_from_db()
        self.assertTrue(request_obj.is_deleted)

        self.client.logout()
        self.login_admin()
        admin_response = self.client.get(reverse("admin_trash_panel") + "?section=requests")
        self.assertContains(admin_response, "ТМЦ-PERSONAL")

    def test_burger_trash_badge_counts_personal_items(self):
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.operator,
            updated_by=self.operator,
            request_number="ТМЦ-BADGE",
            request_date=timezone.localdate(),
            is_deleted=True,
        )
        self.login_operator()

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, '<span class="user-menu-count" data-trash-menu-count>1</span>', html=True)

        count_response = self.client.get(reverse("trash_count_data"))
        self.assertEqual(count_response.status_code, 200)
        self.assertEqual(count_response.json(), {"count": 1})

    def test_trash_search_is_live_and_has_no_submit_or_reset_buttons(self):
        self.login_operator()

        response = self.client.get(reverse("trash_panel"))

        self.assertContains(response, 'hx-trigger="input changed delay:450ms from:input[name=\'q\'], submit"')
        self.assertContains(response, 'hx-select=".admin-trash-screen"')
        self.assertNotContains(response, ">Сбросить</a>", html=False)
        self.assertNotContains(response, ">Найти</button>", html=False)
        self.assertContains(response, "Через 90 дней")

    def test_operator_can_clear_personal_trash_without_affecting_admin_trash(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.operator,
            updated_by=self.operator,
            request_number="ТМЦ-CLEAR",
            request_date=timezone.localdate(),
            is_deleted=True,
        )
        self.login_operator()

        response = self.client.post(reverse("trash_clear_personal"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ТМЦ-CLEAR")
        request_obj.refresh_from_db()
        self.assertTrue(request_obj.is_deleted)
        self.client.logout()
        self.login_admin()
        self.assertContains(self.client.get(reverse("admin_trash_panel") + "?section=requests"), "ТМЦ-CLEAR")

    def test_personal_trash_hides_items_older_than_ninety_days_but_admin_keeps_them(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.operator,
            updated_by=self.operator,
            request_number="ТМЦ-OLD",
            request_date=timezone.localdate(),
            is_deleted=True,
        )
        TmcRequest.objects.filter(pk=request_obj.pk).update(updated_at=timezone.now() - timedelta(days=91))
        self.login_operator()

        self.assertNotContains(self.client.get(reverse("trash_panel") + "?section=requests"), "ТМЦ-OLD")
        self.client.logout()
        self.login_admin()
        self.assertContains(self.client.get(reverse("admin_trash_panel") + "?section=requests"), "ТМЦ-OLD")

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
        self.assertIn("admin/base.css?v=20260711-005", admin_css)
        self.assertIn("admin/requests.css?v=20260712-002", admin_css)
        self.assertIn("admin/trash.css?v=20260705-016", admin_css)
        self.assertIn("css/admin.css' %}?v=20260711-006", trash_template)



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
        # Even trashed photos must go through the permission-checked preview
        # endpoint (admin-only there), not a raw /media/... URL.
        self.assertContains(response, reverse("photo_preview", args=[self.organ.pk, photo.pk]))
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
        self.assertContains(response, reverse("photo_preview", args=[self.organ.pk, photo.pk]))
        self.assertContains(response, "nested-preview.png")
        self.assertContains(response, "Удалить папку")
        self.assertNotContains(response, ">Очистить</button>")

    def test_trash_folder_tree_previews_do_not_scale_per_root_folder(self):
        # Regression test: _attach_folder_tree_previews used to walk each
        # root folder's descendant tree independently (one query per
        # tree-depth level, per folder, plus a folders query and a photos
        # query per folder). It's now batched across the whole trash page,
        # so the query count for building tree previews should stay flat
        # as the number of root folders on the page grows, not multiply.
        self.login_admin()

        def make_root_with_children(index):
            root = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name=f"Корень {index}", created_by=self.admin, updated_by=self.admin, is_deleted=True)
            child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=root, name=f"Подпапка {index}", created_by=self.admin, updated_by=self.admin, is_deleted=True)
            TerritorialOrganPhoto.objects.create(territorial_organ=self.organ, folder=child, image=self.uploaded_image(f"leaf-{index}.png"), created_by=self.admin, updated_by=self.admin, is_deleted=True)

        for index in range(3):
            make_root_with_children(index)
        def folder_tree_query_count(queries_context):
            return len(
                [
                    q
                    for q in queries_context.captured_queries
                    if "directory_territorialorganphotofolder" in q["sql"].lower() or "directory_territorialorganphoto" in q["sql"].lower()
                ]
            )

        with CaptureQueriesContext(connection) as few_queries:
            response = self.client.get(reverse("admin_trash_panel") + "?section=folders")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["folder_page"].paginator.count, 3)
        few_count = folder_tree_query_count(few_queries)

        for index in range(3, 15):
            make_root_with_children(index)
        with CaptureQueriesContext(connection) as many_queries:
            response = self.client.get(reverse("admin_trash_panel") + "?section=folders")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["folder_page"].paginator.count, 15)
        many_count = folder_tree_query_count(many_queries)

        # Same page size (TRASH_PAGE_SIZE=30 covers both 3 and 15 root folders
        # in a single page), so a flat batched implementation issues the same
        # number of folder/photo queries regardless of how many roots are on
        # that page - isolated from unrelated session-save noise.
        self.assertEqual(few_count, many_count)

    def test_trash_restore_child_folder_warning_uses_visible_alert(self):
        self.login_admin()
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Родитель", created_by=self.admin, updated_by=self.admin, is_deleted=True)
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Подпапка", created_by=self.admin, updated_by=self.admin, is_deleted=True)

        response = self.client.post(reverse("admin_trash_restore_folder", kwargs={"pk": child.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "app-toast alert alert-danger")
        self.assertNotContains(response, "admin-message-stack")
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

    def test_operator_can_restore_deleted_request_in_assigned_department(self):
        self.login_operator()
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.operator,
            updated_by=self.operator,
            request_number="ТМЦ-778",
            request_date=timezone.localdate(),
            is_deleted=True,
        )

        response = self.client.post(reverse("admin_trash_restore_request", kwargs={"table_key": "tmc-requests", "pk": request_obj.pk}))

        self.assertEqual(response.status_code, 302)
        request_obj.refresh_from_db()
        self.assertFalse(request_obj.is_deleted)

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
