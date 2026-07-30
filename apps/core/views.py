import structlog
from django.http import JsonResponse
from django.views import View
from opentelemetry import trace

logger = structlog.get_logger("apps.core")
tracer = trace.get_tracer("apps.core.views")


class HelloView(View):
    def get(self, request):
        with tracer.start_as_current_span("process_hello_request") as main_span:
            main_span.set_attribute("demo.endpoint", "hello_world")
            main_span.set_attribute("demo.request_method", request.method)

            # Log all available log levels
            logger.debug("hello from debug", log_level="debug", sample_data="debug_value")

            with tracer.start_as_current_span("fetch_greeting_data") as sub_span1:
                sub_span1.set_attribute("greeting.source", "internal_service")
                logger.info("hello from info", log_level="info", greeting="Hello World")

            with tracer.start_as_current_span("format_greeting_response") as sub_span2:
                sub_span2.set_attribute("response.format", "json")
                sub_span2.set_attribute("response.status_code", 200)

                logger.warning("hello from warning", log_level="warning", warning_code="DEMO_WARN_001")
                logger.error("hello from error", log_level="error", error_code="DEMO_ERR_500")
                logger.critical("hello from critical", log_level="critical", alert_level="P1")

            return JsonResponse(
                {
                    "message": "Hello World",
                    "status": "success",
                    "telemetry": {
                        "tracing": "enabled",
                        "metrics": "enabled",
                        "logs": "enabled",
                    },
                }
            )
