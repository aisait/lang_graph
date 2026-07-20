"""
telemetry_otel.py
Inicialización de OpenTelemetry para Langfuse v4 (nativo OTLP).
Cumple con ISO/IEC 27001 (gestión de secretos), DORA (resiliencia),
y pruebas de caja negra ISO/IEC 29119.

Funcionalidad:
- Configura el TracerProvider con exporter OTLP a Langfuse.
- Autentica usando Basic Auth (clave pública/secreta en variables de entorno).
- Instrumenta automáticamente FastAPI, LangChain, OpenAI, HTTP/HTTPS.
- Proporciona get_tracer() para spans manuales en el código de negocio.

Pruebas de caja negra (ISO/IEC 29119):
1. Inicialización sin credenciales: debe desactivar telemetría y devolver False.
2. Inicialización con credenciales válidas: debe configurar tracer y devolver True.
3. Auto-instrumentación: al hacer una petición HTTP o llamada a OpenAI, deben aparecer spans en Langfuse.
"""
import os
import base64
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXInstrumentor

logger = logging.getLogger(__name__)

def init_telemetry(app=None):
    """
    Inicializa OpenTelemetry con exportación a Langfuse v4.
    Args:
        app: Instancia de FastAPI (opcional) para instrumentación automática.
    Returns:
        bool: True si se inicializó correctamente, False en caso contrario.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse no configurado - telemetría desactivada")
        return False

    # Autenticación Basic para OTLP (ISO 27001: gestión de secretos)
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{host}/api/public/otel"
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth}"
    os.environ["OTEL_SERVICE_NAME"] = "jarvi-backend"

    # Configurar TracerProvider con BatchSpanProcessor (eficiencia DORA)
    trace_provider = TracerProvider()
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter())
    )
    trace.set_tracer_provider(trace_provider)

    # Auto-instrumentación de librerías clave
    try:
        LangchainInstrumentor().instrument()
        OpenAIInstrumentor().instrument()
        RequestsInstrumentor().instrument()
        HTTPXInstrumentor().instrument()
        if app:
            FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry inicializado con Langfuse v4")
        return True
    except Exception as e:
        logger.error(f"Error en instrumentación automática: {e}")
        return False

def get_tracer(name: str = "jarvi"):
    """Obtiene un tracer para spans manuales."""
    return trace.get_tracer(name)
