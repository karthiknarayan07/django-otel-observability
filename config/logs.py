import atexit
import logging
import os
import re
import socket
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import colorama
import pytz
import structlog
from django.conf import settings
from django.dispatch import receiver
from django.utils import timezone
from django_structlog import signals
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import format_span_id, format_trace_id, get_current_span

from shared.utils import get_from_env

BASE_DIR = Path(__file__).resolve().parent.parent
LOGGING_DIR = os.path.join(BASE_DIR, "logs")

if not os.path.exists(LOGGING_DIR):
    os.makedirs(LOGGING_DIR, exist_ok=True)

DEFAULT_LOG_LEVEL = get_from_env("DJANGO_LOG_LEVEL", "DEBUG")

_HOSTNAME = socket.gethostname()
_SERVICE_NAME = get_from_env("SERVICE_NAME", "django-otel-observability")
_SERVICE_VERSION = get_from_env("SERVICE_VERSION", "1.0.0")

_LOGGER_PROVIDER = None
_LOGGING_HANDLER = None
_LOGGING_INSTRUMENTED = False
_OTEL_LOGGER_NAMES = ("default", "django.request", "django", "apps.core")

_DJANGO_SERVER_LOG_REGEX = re.compile(r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE) ([^ ]+) HTTP/\d+\.\d+"')

colorama.init(autoreset=True)

LEVEL_COLORS = {
    "debug": colorama.Fore.CYAN,
    "info": colorama.Fore.GREEN,
    "warning": colorama.Fore.YELLOW,
    "error": colorama.Fore.RED,
    "critical": colorama.Fore.RED + colorama.Style.BRIGHT,
}


class ColorLogFmtRenderer:
    """Custom structlog renderer for colorized logfmt output on stdout."""

    def __init__(self, key_color=colorama.Fore.CYAN, reset_color=colorama.Style.RESET_ALL):
        self.key_color = key_color
        self.reset_color = reset_color

    def __call__(self, logger, name, event_dict):
        level = str(event_dict.get("level", "info")).lower()
        level_color = LEVEL_COLORS.get(level, colorama.Fore.WHITE)

        keys = list(event_dict.keys())
        priority_keys = ["timestamp", "level", "event"]
        ordered_keys = [k for k in priority_keys if k in keys] + [k for k in keys if k not in priority_keys]

        formatted_items = []
        for key in ordered_keys:
            val = event_dict[key]
            if isinstance(val, str):
                if " " in val or "=" in val or '"' in val:
                    escaped = val.replace('"', '\\"')
                    val_str = f'"{escaped}"'
                else:
                    val_str = val
            else:
                val_str = str(val)

            if key == "level":
                formatted = f"{self.key_color}level{self.reset_color}={level_color}{val_str}{self.reset_color}"
            elif key == "event":
                formatted = f"{self.key_color}event{self.reset_color}={colorama.Style.BRIGHT}{val_str}{self.reset_color}"
            else:
                formatted = f"{self.key_color}{key}{self.reset_color}={val_str}"

            formatted_items.append(formatted)

        return " ".join(formatted_items)


def add_extra_context_to_logs(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    event_dict["ist_time"] = timezone.now().astimezone(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    event_dict["pid"] = os.getpid()
    event_dict["hostname"] = _HOSTNAME
    event_dict["service_version"] = _SERVICE_VERSION

    span = get_current_span()
    context = span.get_span_context()
    if context.trace_id != 0:
        event_dict["trace_id"] = format_trace_id(context.trace_id)
        event_dict["span_id"] = format_span_id(context.span_id)
        event_dict["service_name"] = _SERVICE_NAME
        event_dict["service_version"] = _SERVICE_VERSION

    event = event_dict.get("event", "")
    if isinstance(event, str):
        server_log_match = _DJANGO_SERVER_LOG_REGEX.search(event)
        if server_log_match:
            raw_path = urlparse(server_log_match.group(1)).path
            event_dict["actual_path"] = raw_path
            event_dict["request_path"] = _resolve_path_to_url_pattern(raw_path)

    return event_dict


foreign_pre_chain = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    add_extra_context_to_logs,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        *foreign_pre_chain,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("default")

class OtelCustomLoggingHandler(LoggingHandler):
    """Logging handler that extracts request_method & request_path to attach as indexed OTel attributes."""

    def _get_attributes(self, record: logging.LogRecord) -> dict:
        attributes = super()._get_attributes(record)
        for key in ("request_method", "request_path"):
            if hasattr(record, key) and getattr(record, key) and key not in attributes:
                attributes[key] = str(getattr(record, key))
        return attributes



    def emit(self, record: logging.LogRecord) -> None:
        if not self.filter(record):
            return

        formatted_msg = self.format(record)
        if isinstance(formatted_msg, str) and formatted_msg.startswith("{"):
            try:
                import json
                data = json.loads(formatted_msg)
                for key in ("request_method", "request_path"):
                    if key in data and data[key]:
                        setattr(record, key, str(data[key]))
            except Exception:
                pass

        super().emit(record)




LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "logfmt_color": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": ColorLogFmtRenderer(),
            "foreign_pre_chain": foreign_pre_chain,
        },
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": foreign_pre_chain,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "logfmt_color",
        },
        "null": {
            "class": "logging.NullHandler",
        },
        "file_write": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": os.path.join(LOGGING_DIR, "django.log"),
            "when": "midnight",
            "interval": 1,
            "backupCount": 100,
            "formatter": "json",
            "encoding": "utf-8",
        },
        "otel": {
            "class": "config.logs.OtelCustomLoggingHandler",
            "level": "NOTSET",
            "formatter": "json",
        },
    },
    "loggers": {
        "default": {"handlers": ["file_write", "console", "otel"], "level": DEFAULT_LOG_LEVEL, "propagate": False},
        "django": {"handlers": ["console", "otel"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["file_write", "console", "otel"], "level": "WARNING", "propagate": False},
        "django_structlog.middlewares.request": {"handlers": ["null"], "level": "ERROR", "propagate": False},
        "apps.core": {"handlers": ["file_write", "console", "otel"], "level": "DEBUG", "propagate": False},
    },
}


def init_otel_logs() -> LoggerProvider | None:
    """Initialize OTLP log exporting"""
    global _LOGGER_PROVIDER
    global _LOGGING_HANDLER
    global _LOGGING_INSTRUMENTED

    if not getattr(settings, "ENABLE_LOGS", False):
        return _LOGGER_PROVIDER

    if _LOGGER_PROVIDER is not None:
        return _LOGGER_PROVIDER

    resource = Resource.create(
        {
            "service.name": getattr(settings, "SERVICE_NAME", "django-otel-observability"),
            "service.version": getattr(settings, "SERVICE_VERSION", "1.0.0"),
        }
    )



    try:
        logger_provider = LoggerProvider(resource=resource)
        exporter_timeout_seconds = getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000) / 1000.0
        log_exporter = OTLPLogExporter(
            endpoint=getattr(settings, "OTEL_GRPC_ENDPOINT", "localhost:4317"),
            headers=getattr(settings, "OTEL_HEADERS", None),
            insecure=True,
            timeout=exporter_timeout_seconds,
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                log_exporter,
                max_queue_size=getattr(settings, "OTEL_BLRP_MAX_QUEUE_SIZE", 2048),
                schedule_delay_millis=getattr(settings, "OTEL_BLRP_SCHEDULE_DELAY_MILLIS", 1000),
                max_export_batch_size=getattr(settings, "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE", 512),
                export_timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000),
            )
        )
        set_logger_provider(logger_provider)

        if not _LOGGING_INSTRUMENTED:
            LoggingInstrumentor().instrument()
            _LOGGING_INSTRUMENTED = True

        if _LOGGING_HANDLER is None:
            _LOGGING_HANDLER = OtelCustomLoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

        for logger_name in _OTEL_LOGGER_NAMES:
            target_logger = logging.getLogger(logger_name)
            for handler in target_logger.handlers:
                if isinstance(handler, LoggingHandler):
                    handler._logger_provider = logger_provider
            if _LOGGING_HANDLER not in target_logger.handlers:
                target_logger.addHandler(_LOGGING_HANDLER)



        _LOGGER_PROVIDER = logger_provider
        atexit.register(shutdown_otel_logs)
    except Exception:
        logger.exception("Failed to initialize OTLP log export")

    return _LOGGER_PROVIDER


def shutdown_otel_logs():
    """Shutdown OTLP log exporting"""
    global _LOGGER_PROVIDER
    global _LOGGING_HANDLER

    if _LOGGER_PROVIDER is not None:
        if hasattr(_LOGGER_PROVIDER, "force_flush"):
            _LOGGER_PROVIDER.force_flush(timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000))
        if hasattr(_LOGGER_PROVIDER, "shutdown"):
            _LOGGER_PROVIDER.shutdown()
        _LOGGER_PROVIDER = None

    if _LOGGING_HANDLER is not None:
        for logger_name in _OTEL_LOGGER_NAMES:
            target_logger = logging.getLogger(logger_name)
            if _LOGGING_HANDLER in target_logger.handlers:
                target_logger.removeHandler(_LOGGING_HANDLER)
        _LOGGING_HANDLER = None


@contextmanager
def log_context_manager(**kwargs):
    structlog.contextvars.bind_contextvars(**kwargs)
    try:
        yield
    finally:
        structlog.contextvars.clear_contextvars()


@receiver(signals.bind_extra_request_metadata)
def bind_extra_request_metadata(request, logger, log_kwargs, **kwargs):
    try:
        structlog.contextvars.bind_contextvars(
            actual_path=request.path,
            request_path=request.path,
            request_method=request.method,
        )
    except Exception:
        pass


@receiver(signals.bind_extra_request_finished_metadata)
def bind_extra_request_finished_metadata(request, response, logger, log_kwargs, **kwargs):
    structlog.contextvars.bind_contextvars(
        actual_path=request.path,
        request_path=get_url_pattern_path(request),
        request_method=request.method,
        response_status_code=response.status_code,
    )


@receiver(signals.bind_extra_request_failed_metadata)
def bind_extra_request_failed_metadata(request, logger, exception, log_kwargs, **kwargs):
    structlog.contextvars.bind_contextvars(
        actual_path=request.path,
        request_path=get_url_pattern_path(request),
        request_method=request.method,
    )


def get_url_pattern_path(request) -> str:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match and resolver_match.route:
        route = resolver_match.route
        return f"/{route}" if not route.startswith("/") else route
    return ""


def _resolve_path_to_url_pattern(path: str) -> str:
    try:
        from django.urls import resolve
        match = resolve(path)
        if match and match.route:
            route = match.route
            return f"/{route}" if not route.startswith("/") else route
    except Exception:
        pass
    return ""
