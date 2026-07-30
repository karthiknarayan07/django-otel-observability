import os
import django
from django.core.handlers.wsgi import WSGIHandler
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.development")

ENABLE_LOGS = os.environ.get("ENABLE_LOGS", "True") == "True"
ENABLE_TRACING = os.environ.get("ENABLE_TRACING", "True") == "True"
ENABLE_METRICS = os.environ.get("ENABLE_METRICS", "True") == "True"

if ENABLE_TRACING:
    from config.tracing import init_tracer
    init_tracer()

django.setup(set_prefix=False)

from config.logs import init_otel_logs
from config.metrics import init_metrics

try:
    if ENABLE_LOGS:
        init_otel_logs()
    if ENABLE_METRICS:
        init_metrics()
except Exception:
    import logging
    logging.exception("Failed to initialize OpenTelemetry telemetry in WSGI application")

application = WSGIHandler()
