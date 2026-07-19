from pathlib import Path
import os

import environ


BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.directory.apps.DirectoryConfig",
    "apps.requests_app.apps.RequestsAppConfig",
    "apps.audit.apps.AuditConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.RequestAuditMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
if "postgresql" in DATABASES["default"]["ENGINE"]:
    # Reuse connections between requests instead of paying for a PostgreSQL
    # TCP/authentication handshake on every view. Health checks make a worker
    # recover cleanly after a database restart or connection timeout.
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
if "sqlite3" in DATABASES["default"]["ENGINE"]:
    # Default busy timeout is 5s - a long-running write (e.g. the demo data
    # generator) can hold SQLite's single writer lock past that under any
    # concurrent write (session saves, presence pings), surfacing as
    # "database is locked" instead of just waiting a bit longer.
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20

    # SQLite's default rollback-journal mode blocks readers while a writer
    # transaction is open, on top of only ever allowing one writer at a
    # time - WAL mode lets readers (e.g. the seed generator's progress-bar
    # polling) proceed without waiting on an in-progress write, which the
    # timeout increase above doesn't help with. No-ops harmlessly for the
    # in-memory database used in tests.
    from django.db.backends.signals import connection_created

    def _set_sqlite_wal_mode(sender, connection, **kwargs):
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode=WAL;")

    connection_created.connect(_set_sqlite_wal_mode)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Krasnoyarsk"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_ROOT", default="media")
ADMIN_THRESHOLDS_FILE = BASE_DIR / env(
    "ADMIN_THRESHOLDS_FILE",
    default="dashboard_thresholds.json",
)
# Bulk photo upload must accept 300+ files in a single request even without
# the JS batching (locked by test_photo_bulk_upload_accepts_more_than_300_files),
# so 500 keeps that working while still bounding what a malicious or broken
# client can post in one request (previously unlimited).
DATA_UPLOAD_MAX_NUMBER_FILES = 500

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TEST_RUNNER = "config.test_runner.QuietRequestLogTestRunner"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
# Authentication already updates the session when its contents change.
# Saving every read-only request adds an unnecessary database UPDATE and is
# especially costly for polling/HTMX endpoints.
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_HTTPONLY = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

REDIS_URL = env("REDIS_URL", default="").strip()
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": env("CACHE_KEY_PREFIX", default="ais_uzmo"),
            "TIMEOUT": env.int("CACHE_DEFAULT_TIMEOUT", default=300),
        }
        if REDIS_URL
        else {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ais-uzmo-local",
        }
    )
}

if not DEBUG:
    # When the site is served over plain HTTP (e.g. by bare IP without a TLS
    # certificate), Secure cookies would never be sent by the browser and
    # login would silently fail - so these follow SECURE_SSL_REDIRECT, which
    # deployments without HTTPS must set to False in .env.
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
    if SECURE_SSL_REDIRECT:
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "app": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "app"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
