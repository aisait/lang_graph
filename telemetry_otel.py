"""
telemetry_otel.py - OpenTelemetry desactivado para trazabilidad LLM.
Solo se usa para métricas de infraestructura (opcional).
"""
import logging

logger = logging.getLogger(__name__)

def init_telemetry(app=None):
    logger.info("OpenTelemetry desactivado para LLM. Usando SDK de Langfuse.")
    return False

def get_tracer(name: str = "jarvi"):
    from opentelemetry import trace
    return trace.get_tracer(name)

def force_flush():
    pass
