#!/usr/bin/env python
"""Django's command-line utility for administrative tasks with OpenTelemetry instrumentation."""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.development")

    ENABLE_LOGS = os.environ.get("ENABLE_LOGS", "True") == "True"
    ENABLE_TRACING = os.environ.get("ENABLE_TRACING", "True") == "True"
    ENABLE_METRICS = os.environ.get("ENABLE_METRICS", "True") == "True"

    if ENABLE_TRACING:
        from config.tracing import init_tracer
        init_tracer()

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # We import logs and metrics after django imports are resolved
    from config.logs import init_otel_logs
    from config.metrics import init_metrics

    try:
        if ENABLE_LOGS:
            init_otel_logs()
        if ENABLE_METRICS:
            init_metrics()
    except Exception:
        import logging
        logging.exception("Failed to initialize OpenTelemetry telemetry in manage.py")

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
