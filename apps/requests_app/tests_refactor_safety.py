from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import RequestNumberRegistry, TmcRequest, VehicleFuelRequest, VehicleRepairRequest
from apps.requests_app.services.request_numbers import REQUEST_NUMBER_DUPLICATE_MESSAGE


class RequestNumberRegistryRegressionTests(TestCase):
    """Regression tests for the service layer introduced during the refactor."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("operator", password="pass12345")
        self.profile = UserProfile.objects.create(user=self.user, role=UserProfile.Role.OPERATOR)
        self.organ = TerritorialOrgan.objects.create(name="Main territorial organ", order_number=1)
        self.other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.department_tmc = Department.objects.create(name="TMC", slug="tmc", order_number=1)
        self.department_transport = Department.objects.create(name="Transport", slug="transport", order_number=2)
        self.profile.allowed_organs.set([self.organ, self.other_organ])
        self.profile.allowed_departments.set([self.department_tmc, self.department_transport])
        self.client.login(username="operator", password="pass12345")

    def post_vehicle_repair(self, organ, request_number, **overrides):
        payload = {
            "request_number": request_number,
            "request_date": "2026-07-01",
            "status": "in_work",
            "comment": overrides.pop("comment", "Repair request"),
        }
        payload.update(overrides)
        return self.client.post(
            reverse("record_create", args=[organ.pk, "vehicle-repair"]),
            payload,
            HTTP_HX_REQUEST="true",
        )

    def post_vehicle_fuel(self, organ, request_number, **overrides):
        payload = {
            "request_number": request_number,
            "request_date": "2026-07-01",
            "status": "in_work",
            "comment": overrides.pop("comment", "Fuel request"),
        }
        payload.update(overrides)
        return self.client.post(
            reverse("record_create", args=[organ.pk, "vehicle-fuel"]),
            payload,
            HTTP_HX_REQUEST="true",
        )

    def post_tmc_request(self, organ, request_number, **overrides):
        payload = {
            "request_number": request_number,
            "request_date": "2026-07-01",
            "status": "in_work",
            "comment": overrides.pop("comment", "TMC request"),
            "item_name": [overrides.pop("item_name", "Paper")],
            "item_quantity": [overrides.pop("item_quantity", "1")],
            "item_unit": [overrides.pop("item_unit", "шт.")],
        }
        payload.update(overrides)
        return self.client.post(
            reverse("record_create", args=[organ.pk, "tmc-requests"]),
            payload,
            HTTP_HX_REQUEST="true",
        )

    def test_duplicate_number_is_blocked_across_tables_inside_one_department(self):
        first_response = self.post_vehicle_repair(self.organ, "  TR-001  ")
        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(VehicleRepairRequest.objects.filter(request_number="TR-001").exists())
        self.assertTrue(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                department="transport",
                request_number="TR-001",
                normalized_request_number="tr-001",
            ).exists()
        )

        duplicate_response = self.post_vehicle_fuel(self.organ, "tr-001")

        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(duplicate_response, REQUEST_NUMBER_DUPLICATE_MESSAGE)
        self.assertFalse(VehicleFuelRequest.objects.filter(request_number="tr-001").exists())
        self.assertEqual(RequestNumberRegistry.objects.filter(territorial_organ=self.organ, department="transport").count(), 1)

    def test_same_number_is_allowed_for_other_organ_and_registry_keeps_both_rows(self):
        self.post_vehicle_repair(self.organ, "TR-002")

        other_response = self.post_vehicle_fuel(self.other_organ, "tr-002")

        self.assertEqual(other_response.status_code, 200)
        self.assertTrue(VehicleFuelRequest.objects.filter(territorial_organ=self.other_organ, request_number="tr-002").exists())
        self.assertEqual(RequestNumberRegistry.objects.filter(department="transport", normalized_request_number="tr-002").count(), 2)

    def test_same_number_is_allowed_for_other_department_in_same_organ(self):
        self.post_vehicle_repair(self.organ, "CROSS-001")

        response = self.post_tmc_request(self.organ, "cross-001")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TmcRequest.objects.filter(territorial_organ=self.organ, request_number="cross-001").exists())
        self.assertEqual(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                normalized_request_number="cross-001",
            ).count(),
            2,
        )
        self.assertTrue(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                department="transport",
                normalized_request_number="cross-001",
            ).exists()
        )
        self.assertTrue(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                department="tmc",
                normalized_request_number="cross-001",
            ).exists()
        )

    def test_update_to_existing_number_is_rejected_without_rewriting_registry(self):
        self.post_vehicle_repair(self.organ, "TR-006")
        self.post_vehicle_fuel(self.organ, "TR-007")
        fuel_request = VehicleFuelRequest.objects.get(request_number="TR-007")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-fuel", fuel_request.pk]),
            {
                "request_number": "tr-006",
                "request_date": "2026-07-02",
                "status": "done",
                "completed_at": "2026-07-03",
                "comment": "Try duplicate on update",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, REQUEST_NUMBER_DUPLICATE_MESSAGE)
        fuel_request.refresh_from_db()
        self.assertEqual(fuel_request.request_number, "TR-007")
        self.assertEqual(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                department="transport",
                normalized_request_number="tr-006",
            ).count(),
            1,
        )
        self.assertTrue(
            RequestNumberRegistry.objects.filter(
                territorial_organ=self.organ,
                department="transport",
                normalized_request_number="tr-007",
                object_id=fuel_request.pk,
            ).exists()
        )

    def test_delete_releases_number_for_reuse_in_same_department(self):
        self.post_vehicle_repair(self.organ, "TR-003")
        request_obj = VehicleRepairRequest.objects.get(request_number="TR-003")

        delete_response = self.client.post(
            reverse("record_delete", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            HTTP_HX_REQUEST="true",
        )
        reuse_response = self.post_vehicle_fuel(self.organ, "tr-003")

        self.assertEqual(delete_response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertTrue(request_obj.is_deleted)
        self.assertEqual(reuse_response.status_code, 200)
        self.assertTrue(VehicleFuelRequest.objects.filter(request_number="tr-003").exists())
        self.assertEqual(RequestNumberRegistry.objects.filter(territorial_organ=self.organ, department="transport").count(), 1)

    def test_update_can_keep_same_number_after_normalization(self):
        self.post_vehicle_repair(self.organ, "TR-004")
        request_obj = VehicleRepairRequest.objects.get(request_number="TR-004")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            {
                "request_number": "  tr-004  ",
                "request_date": "2026-07-02",
                "status": "done",
                "completed_at": "2026-07-03",
                "comment": "Completed",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.request_number, "tr-004")
        self.assertEqual(RequestNumberRegistry.objects.filter(territorial_organ=self.organ, department="transport").count(), 1)


class ThinViewRegressionSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("operator", password="pass12345")
        self.profile = UserProfile.objects.create(user=self.user, role=UserProfile.Role.OPERATOR)
        self.organ = TerritorialOrgan.objects.create(name="Main territorial organ", order_number=1)
        self.department_tmc = Department.objects.create(name="TMC", slug="tmc", order_number=1)
        self.department_transport = Department.objects.create(name="Transport", slug="transport", order_number=2)
        self.profile.allowed_organs.set([self.organ])
        self.profile.allowed_departments.set([self.department_tmc, self.department_transport])
        self.client.login(username="operator", password="pass12345")

    def test_main_refactored_table_endpoints_render_without_server_error(self):
        VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="SMOKE-R",
            request_date="2026-07-01",
            status="in_work",
            comment="Smoke repair",
        )
        VehicleFuelRequest.objects.create(
            territorial_organ=self.organ,
            request_number="SMOKE-F",
            request_date="2026-07-01",
            status="done",
            comment="Smoke fuel",
        )

        endpoints = [
            reverse("dashboard"),
            reverse("organ_info", args=[self.organ.pk]),
            reverse("table_data", args=[self.organ.pk, "vehicle-repair"]),
            reverse("table_data", args=[self.organ.pk, "vehicle-fuel"]),
            reverse("export_table", args=[self.organ.pk, "vehicle-repair", "csv"]),
            reverse("export_table", args=[self.organ.pk, "vehicle-fuel", "xlsx"]),
        ]

        for url in endpoints:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertLess(response.status_code, 500)


class SearchPerformanceRegressionTests(TestCase):
    def test_search_helpers_do_not_iterate_full_querysets_in_python(self):
        files = {
            "apps/requests_app/services/table_filters.py": [
                "matched_ids = [obj.pk for obj in qs",
                "object_matches_casefold_search",
            ],
            "apps/requests_app/services/photo_assets.py": [
                "for photo in qs if photo_matches_query",
                "query_normalized in folder.name.casefold()",
            ],
            "apps/requests_app/services/request_photos.py": [
                "for photo in scoped_qs",
                "query_normalized in photo.description.casefold()",
            ],
            "apps/requests_app/services/tmc.py": [
                "for product in TmcProduct.objects.filter(is_active=True):",
            ],
        }
        for path, forbidden_snippets in files.items():
            with self.subTest(path=path):
                source = open(path, encoding="utf-8").read()
                for snippet in forbidden_snippets:
                    self.assertNotIn(snippet, source)

    def test_tmc_suggestions_keep_typo_match_after_candidate_prefilter(self):
        from apps.requests_app.services.tmc import tmc_product_suggestions
        from apps.requests_app.models import TmcProduct

        for index in range(30):
            TmcProduct.objects.create(name=f"Канцелярский набор {index}", unit="шт.")
        TmcProduct.objects.create(name="Пылесос", unit="шт.")
        TmcProduct.objects.create(name="Пылесборник", unit="шт.")

        suggestions = tmc_product_suggestions("пылксос")

        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].name, "Пылесос")


class RequestsAppTestsSplitRegressionTests(TestCase):
    def test_requests_app_tests_are_split_into_thematic_modules(self):
        expected_modules = [
            "apps/requests_app/tests_core.py",
            "apps/requests_app/tests_tmc.py",
            "apps/requests_app/tests_tables.py",
            "apps/requests_app/tests_photos.py",
            "apps/requests_app/tests_seed.py",
        ]
        for module_path in expected_modules:
            with self.subTest(module_path=module_path):
                self.assertTrue(open(module_path, encoding="utf-8").read().strip())

        monolith_lines = open("apps/requests_app/tests.py", encoding="utf-8").read().splitlines()
        self.assertLessEqual(len(monolith_lines), 80)

        for module_path in expected_modules:
            with self.subTest(module_path=module_path):
                self.assertIn("class ", open(module_path, encoding="utf-8").read())
