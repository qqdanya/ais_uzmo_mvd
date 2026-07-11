from contextlib import contextmanager
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from .services.export_limits import HEAVY_EXPORT_MAX_CONCURRENT, ExportBusyError, heavy_export_slot
from .tests_base import *


@contextmanager
def force_heavy_export():
    with patch("apps.requests_app.services.table_exports.should_use_write_only", return_value=True):
        yield


class HeavyExportSlotTests(TestCase):

    def tearDown(self):
        cache.clear()

    def test_allows_up_to_the_concurrency_limit(self):
        with heavy_export_slot():
            with heavy_export_slot():
                pass  # HEAVY_EXPORT_MAX_CONCURRENT is 2 - both should acquire fine.

    def test_rejects_once_every_slot_is_taken(self):
        with heavy_export_slot():
            with heavy_export_slot():
                with self.assertRaises(ExportBusyError):
                    with heavy_export_slot():
                        pass

    def test_slot_is_released_after_use_for_the_next_export(self):
        for _ in range(HEAVY_EXPORT_MAX_CONCURRENT + 3):
            with heavy_export_slot():
                pass  # Each one must release before the next acquires, or this raises.

    def test_slot_is_released_even_if_the_export_raises(self):
        with self.assertRaises(RuntimeError):
            with heavy_export_slot():
                raise RuntimeError("export blew up")

        with heavy_export_slot():
            pass  # The slot from the failed export above must have been freed.


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "heavy-export-test"}})
class HeavyExportViaTableTests(RequestAppTestCase):

    def tearDown(self):
        cache.clear()

    def test_small_export_ignores_a_fully_occupied_semaphore(self):
        # Exports below the styling row-count cutoff never touch the slots at
        # all, so a small export must succeed even with every slot taken.
        for index in range(HEAVY_EXPORT_MAX_CONCURRENT):
            cache.add(f"heavy-export-slot:{index}", "someone-else", timeout=150)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-inventory", "xlsx"]))

        self.assertEqual(response.status_code, 200)

    def test_busy_semaphore_redirects_a_heavy_export_with_an_error_message(self):
        for index in range(HEAVY_EXPORT_MAX_CONCURRENT):
            cache.add(f"heavy-export-slot:{index}", "someone-else", timeout=150)
        self.client.login(username="operator", password="pass12345")

        with force_heavy_export():
            response = self.client.get(
                reverse("export_table", args=[self.organ.pk, "vehicle-inventory", "xlsx"]), follow=True
            )

        self.assertContains(response, "Сейчас уже выполняется несколько больших экспортов")

    def test_heavy_export_succeeds_and_releases_its_slot_when_free(self):
        self.client.login(username="operator", password="pass12345")

        with force_heavy_export():
            response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-inventory", "xlsx"]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(cache.get("heavy-export-slot:0"))
        self.assertIsNone(cache.get("heavy-export-slot:1"))
