import logging

from django.test.runner import DiscoverRunner


class QuietRequestLogTestRunner(DiscoverRunner):
    """Raises django.request to ERROR for the run so expected 403/404 WARNING
    noise (permission and not-found tests) doesn't bury a real 500 failure.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._request_logger = logging.getLogger("django.request")
        self._request_logger_level = self._request_logger.level
        self._request_logger.setLevel(logging.ERROR)

    def teardown_test_environment(self, **kwargs):
        self._request_logger.setLevel(self._request_logger_level)
        super().teardown_test_environment(**kwargs)
