import os
import subprocess
import sys
import unittest

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_settings_prod(extra_env):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings_prod", **extra_env}
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
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
