# ============================================================
# Observability setup
# Uses configure_azure_monitor() from FoundryChatClient for Foundry projects
#
# CORE SERVICE — do not add domain-specific logic here.
# Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/observability
# Pattern: Third-party Azure Monitor setup with enable_instrumentation()
# ============================================================

import logging
import os

from app.config import get_settings

logger = logging.getLogger(__name__)


def configure_observability() -> None:
    """
    Configure OpenTelemetry instrumentation for the backend.

    For Foundry projects, use client.configure_azure_monitor() which automatically
    retrieves the Application Insights connection string from the Foundry project.

    Reference:
      https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/observability/foundry_tracing.py
    """
    settings = get_settings()

    if not settings.enable_instrumentation:
        logger.info("Observability instrumentation disabled")
        return

    # Configure Python logging to align with OpenTelemetry output
    logging.basicConfig(
        format="[%(asctime)s - %(name)s:%(lineno)d - %(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger().setLevel(logging.INFO)

    # Suppress chatty Azure SDK loggers
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
    logging.getLogger("azure.identity.aio").setLevel(logging.WARNING)

    # Set OTEL service name for trace identification
    os.environ.setdefault("OTEL_SERVICE_NAME", settings.otel_service_name)
    os.environ.setdefault("ENABLE_INSTRUMENTATION", "true")

    if settings.enable_sensitive_data:
        os.environ["ENABLE_SENSITIVE_DATA"] = "true"
        logger.warning(
            "Sensitive data logging is ENABLED — disable in production to avoid PII exposure"
        )

    # If Application Insights connection string is provided, configure Azure Monitor
    if settings.applicationinsights_connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            from agent_framework.observability import create_resource, enable_instrumentation

            configure_azure_monitor(
                connection_string=settings.applicationinsights_connection_string,
                resource=create_resource(),
                enable_live_metrics=True,
            )
            # Activate Agent Framework telemetry code paths
            enable_instrumentation(enable_sensitive_data=settings.enable_sensitive_data)
            logger.info("Azure Monitor observability configured")
        except ImportError:
            logger.warning("azure-monitor-opentelemetry not installed; falling back to console")
            _configure_console_observability()
    else:
        # Development: use console exporter or Aspire Dashboard
        _configure_console_observability()
        logger.info(
            "No Application Insights connection string found. "
            "Set APPLICATIONINSIGHTS_CONNECTION_STRING or use Aspire Dashboard: "
            "docker run -p 18888:18888 -p 4317:18889 mcr.microsoft.com/dotnet/aspire-dashboard:latest"
        )


def _configure_console_observability() -> None:
    """Configure console-based OpenTelemetry (development / Aspire Dashboard)."""
    try:
        from agent_framework.observability import configure_otel_providers
        from opentelemetry.sdk.metrics import view as metrics_view
        from opentelemetry.sdk.metrics._internal.aggregation import DropAggregation

        # Drop noisy internal OTEL SDK self-observability metrics
        _drop_views = [
            metrics_view.View(instrument_name="otel.sdk.*", aggregation=DropAggregation()),
        ]

        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            configure_otel_providers(views=_drop_views)
            logger.info("OTLP observability configured (endpoint: %s)", otlp_endpoint)
        else:
            # No exporter destination — configure providers (instruments/context propagation)
            # without console exporters to avoid noisy JSON span/log dumps in dev
            configure_otel_providers(enable_console_exporters=False, views=_drop_views)
            logger.info(
                "Console observability configured (no exporter — "
                "set OTEL_EXPORTER_OTLP_ENDPOINT to forward telemetry)"
            )
    except Exception as exc:
        logger.warning("Could not configure observability: %s", exc)
