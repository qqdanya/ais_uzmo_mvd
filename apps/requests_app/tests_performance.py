"""Query-count regression tests for the pages users hit most.

These aren't meant to force an exact "ideal" query count - just to catch a
future N+1 regression before it ships. Bounds are set with headroom over the
count measured at the time the test was written (noted per test), not a
target to shrink toward.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .tests_base import *


class PerformanceRegressionTests(RequestAppTestCase):
    def seed_tmc_requests(self, count=10):
        for index in range(count):
            obj = TmcRequest.objects.create(
                territorial_organ=self.organ,
                created_by=self.user,
                request_number=f"perf-{index}",
                request_date="2026-06-20",
                status="in_work",
            )
            TmcRequestItem.objects.create(request=obj, name="Item", quantity=1, unit="шт.")

    def test_dashboard_query_count_has_a_ceiling(self):
        # Measured 12 queries for 10 seeded requests at write time.
        self.seed_tmc_requests()
        self.client.login(username="operator", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 20)

    def test_htmx_table_load_query_count_has_a_ceiling(self):
        # Measured 20 queries for 10 seeded requests at write time.
        self.seed_tmc_requests()
        self.client.login(username="operator", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 30)

    def test_photo_gallery_query_count_has_a_ceiling(self):
        # Measured 27 queries for 10 photos at write time (mild sub-linear
        # scaling observed - not flagged as a bug here, just given headroom).
        for index in range(10):
            self.create_photo(f"perf-{index}.png")
        self.client.login(username="operator", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("photos", args=[self.organ.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 40)

    def test_csv_export_query_count_has_a_ceiling(self):
        # Measured 10 queries for 10 seeded requests at write time.
        self.seed_tmc_requests()
        self.client.login(username="operator", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("export_table", args=[self.organ.pk, "tmc-requests", "csv"]))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 18)

    def test_tmc_xlsx_export_query_count_has_a_ceiling(self):
        # Measured 13 queries for 10 seeded requests at write time.
        self.seed_tmc_requests()
        self.client.login(username="operator", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("export_table", args=[self.organ.pk, "tmc-requests", "xlsx"]))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 20)
