import atexit
from django.conf import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .logs import get_url_pattern_path

_TRACER_PROVIDER = None
_TRACING_INSTRUMENTED = False


def init_tracer():
    """Initialize OpenTelemetry tracer with proper shutdown handling"""
    global _TRACER_PROVIDER
    global _TRACING_INSTRUMENTED

    enable_tracing = getattr(settings, "ENABLE_TRACING", False)
    if not enable_tracing:
        return _TRACER_PROVIDER

    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER

    service_name = getattr(settings, "SERVICE_NAME", "django-otel-observability")
    service_version = getattr(settings, "SERVICE_VERSION", "1.0.0")
    resource = Resource.create({"service.name": service_name, "service.version": service_version})

    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    otel_endpoint = getattr(settings, "OTEL_GRPC_ENDPOINT", "localhost:4317")
    exporter_timeout_seconds = getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000) / 1000.0

    otlp_exporter = OTLPSpanExporter(
        endpoint=otel_endpoint,
        headers=getattr(settings, "OTEL_HEADERS", None),
        insecure=True,
        timeout=exporter_timeout_seconds,
    )

    span_processor = BatchSpanProcessor(
        otlp_exporter,
        max_queue_size=getattr(settings, "OTEL_BSP_MAX_QUEUE_SIZE", 2048),
        schedule_delay_millis=getattr(settings, "OTEL_BSP_SCHEDULE_DELAY_MILLIS", 1000),
        max_export_batch_size=getattr(settings, "OTEL_BSP_MAX_EXPORT_BATCH_SIZE", 512),
        export_timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000),
    )
    tracer_provider.add_span_processor(span_processor)

    _TRACER_PROVIDER = tracer_provider

    if not _TRACING_INSTRUMENTED:
        DjangoInstrumentor().instrument(
            request_hook=_otel_django_request_hook,
            response_hook=_otel_django_response_hook,
        )
        RequestsInstrumentor().instrument()
        _TRACING_INSTRUMENTED = True

    atexit.register(shutdown_tracer)
    return _TRACER_PROVIDER


def shutdown_tracer():
    """Shutdown OpenTelemetry tracers and processors"""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        if hasattr(_TRACER_PROVIDER, "force_flush"):
            _TRACER_PROVIDER.force_flush(timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000))
        if hasattr(_TRACER_PROVIDER, "shutdown"):
            _TRACER_PROVIDER.shutdown()
        _TRACER_PROVIDER = None


def _otel_django_request_hook(span, request):
    if span and span.is_recording():
        pass


def _otel_django_response_hook(span, request, response):
    if span and span.is_recording():
        request_path = get_url_pattern_path(request)
        span.set_attribute("http.status_code", response.status_code)
        span.set_attribute("http.route", request_path)
        span.set_attribute("http.path", request_path)
