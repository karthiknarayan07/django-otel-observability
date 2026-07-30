import logging
from pathlib import Path

from config.logs import LOGGING  # noqa: F401
from shared.utils import get_from_env, str_to_bool

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = get_from_env("DEBUG", True, type_cast=str_to_bool)
SECRET_KEY = get_from_env("DJANGO_SECRET_KEY", "django-insecure-otel-demo-key")

NAMESPACE = get_from_env("NAMESPACE", "local")
SERVICE_NAME = get_from_env("SERVICE_NAME", "django-otel-observability")
SERVICE_VERSION = get_from_env("SERVICE_VERSION", "1.0.0")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

ROOT_URLCONF = "settings.urls"
WSGI_APPLICATION = "settings.wsgi.application"

ENABLE_TRACING = get_from_env("ENABLE_TRACING", True, type_cast=str_to_bool)
ENABLE_METRICS = get_from_env("ENABLE_METRICS", True, type_cast=str_to_bool)
ENABLE_LOGS = get_from_env("ENABLE_LOGS", True, type_cast=str_to_bool)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # Internal Apps
    "apps.core",
    # Third Party Apps
    "django_structlog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_structlog.middlewares.RequestMiddleware",
    "config.metrics.OpenTelemetryCustomMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

OTEL_GRPC_ENDPOINT = get_from_env("OTEL_GRPC_ENDPOINT", "localhost:4317")
OTEL_HEADERS = {}
OTEL_EXPORTER_TIMEOUT_MILLIS = get_from_env("OTEL_EXPORTER_TIMEOUT_MILLIS", 3000, type_cast=int)
OTEL_BSP_MAX_QUEUE_SIZE = get_from_env("OTEL_BSP_MAX_QUEUE_SIZE", 2048, type_cast=int)
OTEL_BSP_MAX_EXPORT_BATCH_SIZE = get_from_env("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", 512, type_cast=int)
OTEL_BSP_SCHEDULE_DELAY_MILLIS = get_from_env("OTEL_BSP_SCHEDULE_DELAY_MILLIS", 1000, type_cast=int)
OTEL_BLRP_MAX_QUEUE_SIZE = get_from_env("OTEL_BLRP_MAX_QUEUE_SIZE", 2048, type_cast=int)
OTEL_BLRP_MAX_EXPORT_BATCH_SIZE = get_from_env("OTEL_BLRP_MAX_EXPORT_BATCH_SIZE", 512, type_cast=int)
OTEL_BLRP_SCHEDULE_DELAY_MILLIS = get_from_env("OTEL_BLRP_SCHEDULE_DELAY_MILLIS", 1000, type_cast=int)
OTEL_METRIC_EXPORT_INTERVAL_MILLIS = get_from_env("OTEL_METRIC_EXPORT_INTERVAL_MILLIS", 5000, type_cast=int)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"

