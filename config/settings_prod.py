from .settings import *  # noqa

DEBUG = False
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

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
