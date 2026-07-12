import logging
import shutil
import tempfile
import unittest

from django.core.cache import caches
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class CacheClearingTextTestResult(unittest.TextTestResult):
    """Clears every cache before each test.

    The test database is rolled back between tests, but LocMemCache is not -
    it lives for the whole process. Cached values keyed by user pk (e.g. the
    personal trash-count badge) would otherwise leak between tests, because
    rolled-back auto-increment pks get reused by the next test's users.
    """

    def startTest(self, test):
        for cache in caches.all():
            cache.clear()
        super().startTest(test)


class QuietRequestLogTestRunner(DiscoverRunner):
    """Raises django.request to ERROR for the run so expected 403/404 WARNING
    noise (permission and not-found tests) doesn't bury a real 500 failure.

    Also points MEDIA_ROOT at a throwaway temp directory for the run: the
    test database is rolled back after every test, but files that photo
    upload tests save through Django storage are not - without this, every
    suite run leaked another batch of 2x2 test PNGs into the real media/.
    """

    def get_test_runner_kwargs(self):
        kwargs = super().get_test_runner_kwargs()
        kwargs["resultclass"] = CacheClearingTextTestResult
        return kwargs

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._request_logger = logging.getLogger("django.request")
        self._request_logger_level = self._request_logger.level
        self._request_logger.setLevel(logging.ERROR)
        self._media_root = tempfile.mkdtemp(prefix="test-media-")
        self._media_override = override_settings(MEDIA_ROOT=self._media_root)
        self._media_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._media_override.disable()
        shutil.rmtree(self._media_root, ignore_errors=True)
        self._request_logger.setLevel(self._request_logger_level)
        super().teardown_test_environment(**kwargs)
