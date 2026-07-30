import atexit
from timeit import default_timer
import structlog
from django.conf import settings
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource

from .logs import get_url_pattern_path

logger = structlog.getLogger("default")

_METER_PROVIDER = None
_METER = None
_INSTRUMENTS = {}
_INITIALIZED = False


def init_metrics() -> tuple[metrics.Meter, dict]:
    """Initialize OpenTelemetry metrics with proper shutdown handling"""
    global _METER_PROVIDER, _METER, _INITIALIZED, _INSTRUMENTS

    if _INITIALIZED:
        assert _METER is not None
        return _METER, _INSTRUMENTS

    enable_metrics = getattr(settings, "ENABLE_METRICS", False)
    if not enable_metrics:
        return _METER, _INSTRUMENTS

    otel_endpoint = getattr(settings, "OTEL_GRPC_ENDPOINT", "localhost:4317")
    exporter_timeout_seconds = getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000) / 1000.0

    otlp_exporter = OTLPMetricExporter(
        endpoint=otel_endpoint,
        headers=getattr(settings, "OTEL_HEADERS", None),
        insecure=True,
        timeout=exporter_timeout_seconds,
    )

    metric_reader = PeriodicExportingMetricReader(
        otlp_exporter,
        export_interval_millis=getattr(settings, "OTEL_METRIC_EXPORT_INTERVAL_MILLIS", 5000),
        export_timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000),
    )

    http_metric_attribute_keys = {"request_path", "method", "status_code"}

    http_requests_total_view = View(
        instrument_name="http_requests_total",
        attribute_keys=http_metric_attribute_keys,
    )

    http_request_duration_seconds_histogram_view = View(
        instrument_name="http_request_duration_seconds",
        attribute_keys=http_metric_attribute_keys,
        aggregation=ExplicitBucketHistogramAggregation(
            boundaries=[0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30]
        ),
    )

    resource = Resource(
        {
            "service.name": getattr(settings, "SERVICE_NAME", "django-otel-observability"),
            "service.version": getattr(settings, "SERVICE_VERSION", "1.0.0"),
        }
    )


    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
        views=[
            http_requests_total_view,
            http_request_duration_seconds_histogram_view,
        ],
    )
    metrics.set_meter_provider(meter_provider)

    meter = metrics.get_meter(__name__)

    instruments = {
        "http_requests_total_count": meter.create_counter("http_requests_total", description="Total HTTP requests"),
        "http_request_duration_seconds_histogram": meter.create_histogram(
            "http_request_duration_seconds", description="HTTP request latency in seconds"
        ),
    }

    _METER_PROVIDER = meter_provider
    _METER = meter
    _INSTRUMENTS = instruments
    _INITIALIZED = True

    atexit.register(shutdown_metrics)
    return meter, instruments


def shutdown_metrics():
    """Shutdown OpenTelemetry metrics provider"""
    global _METER_PROVIDER
    if _METER_PROVIDER is not None:
        if hasattr(_METER_PROVIDER, "force_flush"):
            _METER_PROVIDER.force_flush(timeout_millis=getattr(settings, "OTEL_EXPORTER_TIMEOUT_MILLIS", 3000))
        if hasattr(_METER_PROVIDER, "shutdown"):
            _METER_PROVIDER.shutdown()
        _METER_PROVIDER = None


class OpenTelemetryCustomMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        _, self._instruments = init_metrics()

    def __call__(self, request):
        start = default_timer()
        response = self.get_response(request)
        duration = default_timer() - start

        actual_path = request.path
        status_code = response.status_code
        if "metrics" in actual_path or "health" in actual_path or status_code == 404:
            return response

        normalized_path = get_url_pattern_path(request)

        if getattr(settings, "ENABLE_METRICS", False) and self._instruments:
            attrs = {
                "request_path": normalized_path or actual_path,
                "method": request.method,
                "status_code": str(status_code),
            }
            try:
                self._instruments["http_requests_total_count"].add(1, attributes=attrs)
                self._instruments["http_request_duration_seconds_histogram"].record(duration, attributes=attrs)
            except Exception:
                logger.exception("Error while recording OTel HTTP request metrics")

        return response
