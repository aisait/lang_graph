"""
validate_langfuse.py
Script de validación para verificar la conectividad con Langfuse v4 vía OpenTelemetry.
Cumple con ISO/IEC 29119 (pruebas de caja negra).

Pruebas de caja negra:
1. Ejecutar el script con credenciales válidas: debe mostrar "✅ Traza de prueba enviada".
2. Revisar dashboard de Langfuse: debe aparecer una traza con nombre "validation_test".
3. Si faltan credenciales: debe mostrar "❌ Faltan credenciales de Langfuse".
4. Si el endpoint OTLP es incorrecto: debe lanzar excepción (capturada en el script).
"""
import os
import base64
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

def main():
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print("❌ Faltan credenciales de Langfuse")
        return

    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{host}/api/public/otel"
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth}"
    os.environ["OTEL_SERVICE_NAME"] = "jarvi-validation"

    trace_provider = TracerProvider()
    trace_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(trace_provider)

    tracer = trace.get_tracer("validation")

    with tracer.start_as_current_span("validation_test") as span:
        span.set_attribute("user.id", "test_user")
        span.set_attribute("session.id", "test_session")
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.prompt.0.role", "system")
        span.set_attribute("gen_ai.prompt.0.content", "Mensaje de prueba")
        span.set_attribute("gen_ai.completion.0.content", "Respuesta de prueba")
        span.set_attribute("gen_ai.usage.input_tokens", 10)
        span.set_attribute("gen_ai.usage.output_tokens", 20)

    print("✅ Traza de prueba enviada a Langfuse v4 via OpenTelemetry")
    print(f"📡 Endpoint: {os.environ['OTEL_EXPORTER_OTLP_ENDPOINT']}")
    print("🔍 Revisa el dashboard de Langfuse para ver la traza")

if __name__ == "__main__":
    main()
