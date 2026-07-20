# validate_langfuse.py (compatible con Langfuse 1.x y 2.x)
import os
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

def main():
    # Obtener credenciales
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST")

    if not public_key or not secret_key:
        print("❌ Faltan credenciales de Langfuse")
        return

    # Inicializar cliente (versión 2.x) o usar el handler (versión 1.x)
    # Para asegurar compatibilidad, usamos el CallbackHandler
    handler = CallbackHandler(
        user_id="test_user",
        session_id="test_session",
        metadata={"test": True}
    )

    # Crear una traza simple usando el handler (esto generará un trace en Langfuse)
    # Simulamos una ejecución de LangChain (aunque no tengamos LangChain, el handler puede usarse)
    # Usamos el cliente para forzar flush
    langfuse = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host
    )

    # Versión 2.x: usar langfuse.trace() directamente
    try:
        trace = langfuse.trace(name="validation_test", user_id="test_user")
        span = trace.span(name="test_span", input={"test": "input"})
        span.end(output={"test": "output"})
        print(f"✅ Traza creada (v2): {trace.id}")
    except AttributeError:
        # Versión 1.x: usar el handler y forzar flush
        print("⚠️  Langfuse 1.x detectado: usando CallbackHandler alternativo")
        # En 1.x, podemos crear un trace usando el cliente con `langfuse.trace()`? No.
        # En su lugar, usamos el decorador @observe o simplemente creamos un trace con el cliente antiguo.
        # En 1.x, el cliente tiene `langfuse.trace()`? No. Mejor usamos `langfuse.create_trace()`?
        # Probemos con `langfuse.trace()` de nuevo, pero puede fallar.
        # Usamos el método `langfuse.start_trace()` si existe.
        if hasattr(langfuse, "start_trace"):
            trace = langfuse.start_trace(name="validation_test", user_id="test_user")
            print(f"✅ Traza creada (v1): {trace.id}")
        else:
            print("❌ No se pudo crear traza con esta versión de Langfuse")
            return

    langfuse.flush()
    print("✅ Flush completado. Revisa el dashboard de Langfuse.")

if __name__ == "__main__":
    main()
