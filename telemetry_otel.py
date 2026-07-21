"""
telemetry_otel.py - Inicialización de OpenTelemetry para infraestructura.
La trazabilidad LLM se maneja exclusivamente con el SDK de Langfuse.
Cumple con ISO/IEC 25010 (eficiencia, fiabilidad) y DORA (resiliencia).
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
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse no configurado - telemetría desactivada")
        return False

    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{host}/api/public/otel"
    # Cabecera crítica para que el worker interprete los datos con el esquema v4
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = (
        f"Authorization=Basic {auth},"
        f"x-langfuse-ingestion-version=4"
    )
    os.environ["OTEL_SERVICE_NAME"] = "jarvi-backend"

    exporter = OTLPSpanExporter(timeout=10)
    trace_provider = TracerProvider()
    span_processor = BatchSpanProcessor(
        exporter,
        max_queue_size=2048,
        schedule_delay_millis=1000,
        max_export_batch_size=512,
        export_timeout_millis=10000,
    )
    trace_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(trace_provider)

    logger.info("OpenTelemetry inicializado (solo infraestructura)")
    return True

def get_tracer(name: str = "jarvi"):
    return trace.get_tracer(name)

def force_flush():
    try:
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'force_flush'):
            provider.force_flush(timeout_millis=5000)
            logger.info("Flush forzado completado")
    except Exception as e:
        logger.error(f"Error en force_flush: {e}")
