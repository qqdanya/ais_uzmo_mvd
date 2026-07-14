import os
import subprocess
import sys
import unittest

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_settings_prod(extra_env, code="import django; django.setup()"):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings_prod", **extra_env}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


class SettingsProdRequiresPostgresTests(unittest.TestCase):
    def test_fails_fast_with_non_postgres_database_url(self):
        # If DATABASE_URL points at (or defaults to, when forgotten in a
        # production .env) anything other than PostgreSQL, prod settings
        # must refuse to start rather than run unnoticed on SQLite.
        result = _load_settings_prod({"DATABASE_URL": "sqlite:///:memory:"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires PostgreSQL", result.stderr)

    def test_loads_with_postgres_database_url(self):
        result = _load_settings_prod(
            {
                "DATABASE_URL": "postgres://user:pass@localhost:5432/dbname",
                "SECRET_KEY": "test-key",
                "ALLOWED_HOSTS": "example.com",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_http_ip_mode_disables_secure_cookies_and_hsts(self):
        result = _load_settings_prod(
            {
                "DATABASE_URL": "postgres://user:pass@localhost:5432/dbname",
                "SECRET_KEY": "test-key",
                "ALLOWED_HOSTS": "127.0.0.1",
                "SECURE_SSL_REDIRECT": "False",
                "SESSION_COOKIE_SECURE": "False",
                "CSRF_COOKIE_SECURE": "False",
                "SECURE_HSTS_SECONDS": "31536000",
                "SECURE_HSTS_INCLUDE_SUBDOMAINS": "True",
                "SECURE_HSTS_PRELOAD": "True",
            },
            code=(
                "import django; django.setup(); "
                "from django.conf import settings; "
                "print(settings.SESSION_COOKIE_SECURE, "
                "settings.CSRF_COOKIE_SECURE, "
                "settings.SECURE_HSTS_SECONDS, "
                "settings.SECURE_HSTS_INCLUDE_SUBDOMAINS, "
                "settings.SECURE_HSTS_PRELOAD)"
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False False 0 False False")

    def test_https_mode_reads_hsts_settings(self):
        result = _load_settings_prod(
            {
                "DATABASE_URL": "postgres://user:pass@localhost:5432/dbname",
                "SECRET_KEY": "test-key",
                "ALLOWED_HOSTS": "example.com",
                "SECURE_SSL_REDIRECT": "True",
                "SECURE_HSTS_SECONDS": "600",
                "SECURE_HSTS_INCLUDE_SUBDOMAINS": "False",
                "SECURE_HSTS_PRELOAD": "False",
            },
            code=(
                "import django; django.setup(); "
                "from django.conf import settings; "
                "print(settings.SESSION_COOKIE_SECURE, "
                "settings.CSRF_COOKIE_SECURE, "
                "settings.SECURE_HSTS_SECONDS, "
                "settings.SECURE_HSTS_INCLUDE_SUBDOMAINS, "
                "settings.SECURE_HSTS_PRELOAD)"
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True 600 False False")
