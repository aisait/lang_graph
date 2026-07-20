"""
telemetry_otel.py - Inicialización de OpenTelemetry con exportador OTLP para Langfuse v4.
Cumple con ISO/IEC 27001, DORA, ISO/IEC 25010.
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
    Retorna True si se configuró correctamente.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse no configurado - telemetría desactivada")
        return False

    # Configurar autenticación Basic para OTLP
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{host}/api/public/otel"
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth}"
    os.environ["OTEL_SERVICE_NAME"] = "jarvi-backend"

    # Crear exportador con logging de errores
    exporter = OTLPSpanExporter(
        timeout=10,  # timeout en segundos
        # Se puede añadir un callback para logging de errores
    )

    # Override del método export para capturar errores
    original_export = exporter.export

    def logged_export(spans):
        try:
            result = original_export(spans)
            # Si el resultado es un Future, esperamos a que termine
            if hasattr(result, 'result'):
                result.result(timeout=15)
            logger.info(f"Exportación OTLP exitosa: {len(spans)} spans")
            return result
        except Exception as e:
            logger.error(f"❌ Error en exportación OTLP: {type(e).__name__}: {e}")
            # No relanzamos para no interrumpir el flujo
            return None

    exporter.export = logged_export

    # Configurar TracerProvider con BatchSpanProcessor (lote pequeño para exportación rápida)
    trace_provider = TracerProvider()
    span_processor = BatchSpanProcessor(
        exporter,
        max_queue_size=512,           # Tamaño máximo de cola
        scheduled_delay_millis=1000,  # Exportar cada 1 segundo
        max_export_batch_size=128,    # Máximo spans por lote
    )
    trace_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(trace_provider)

    logger.info("OpenTelemetry inicializado con Langfuse v4 (instrumentación manual)")
    return True

def get_tracer(name: str = "jarvi"):
    """Obtiene un tracer para spans manuales."""
    return trace.get_tracer(name)

def force_flush():
    """Fuerza la exportación de todos los spans pendientes con timeout."""
    try:
        provider = trace.get_tracer_provider()
        # Si es un TracerProvider, podemos llamar a force_flush
        if hasattr(provider, 'force_flush'):
            provider.force_flush(timeout_millis=5000)
            logger.info("Flush forzado completado")
        else:
            logger.warning("El proveedor no soporta force_flush")
    except Exception as e:
        logger.error(f"Error en force_flush: {e}")
