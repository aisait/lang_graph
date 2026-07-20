"""
telemetry_otel.py
Inicialización de OpenTelemetry para Langfuse v4 (nativo OTLP).
Cumple con ISO/IEC 27001, DORA, ISO/IEC 25010, ISO/IEC 29119.
"""
import os
import base64
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)

def init_telemetry(app=None):
    """
    Inicializa OpenTelemetry con exportación a Langfuse v4.
    Args:
        app: Instancia de FastAPI (opcional) - NO se usa para auto-instrumentación.
    Returns:
        bool: True si se inicializó correctamente, False en caso contrario.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse no configurado - telemetría desactivada")
        return False

    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{host}/api/public/otel"
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth}"
    os.environ["OTEL_SERVICE_NAME"] = "jarvi-backend"

    trace_provider = TracerProvider()
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter())
    )
    trace.set_tracer_provider(trace_provider)

    logger.info("OpenTelemetry inicializado con Langfuse v4 (instrumentación manual)")
    return True

def get_tracer(name: str = "jarvi"):
    """Obtiene un tracer para spans manuales."""
    return trace.get_tracer(name)
