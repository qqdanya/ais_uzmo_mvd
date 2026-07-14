from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa

if "postgresql" not in DATABASES["default"]["ENGINE"]:  # noqa: F405
    raise ImproperlyConfigured(
        "config.settings_prod requires PostgreSQL (set DATABASE_URL to a postgres:// URL). "
        f"Got engine {DATABASES['default']['ENGINE']!r} - if DATABASE_URL is unset in production .env, "  # noqa: F405
        "this silently falls back to SQLite instead of failing loudly."
    )

DEBUG = False
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = env.bool(  # noqa: F405
    "SESSION_COOKIE_SECURE",
    default=SECURE_SSL_REDIRECT,
)
CSRF_COOKIE_SECURE = env.bool(  # noqa: F405
    "CSRF_COOKIE_SECURE",
    default=SECURE_SSL_REDIRECT,
)

# HSTS is meaningful only after the site has working HTTPS. Keeping it at zero
# in the temporary bare-IP/HTTP mode also makes ``check --deploy`` accurately
# report that transport security is not enabled yet.
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)  # noqa: F405
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(  # noqa: F405
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        default=True,
    )
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)  # noqa: F405
else:
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# In addition to stderr (captured by journald via gunicorn), keep a rotating
# on-disk log so incidents can be investigated without journald access.
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))  # noqa: F405
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING["handlers"]["file"] = {  # noqa: F405
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(LOG_DIR / "app.log"),
    "maxBytes": 10 * 1024 * 1024,
    "backupCount": 5,
    "encoding": "utf-8",
    "formatter": "app",
}
LOGGING["root"]["handlers"] = ["console", "file"]  # noqa: F405
