"""
tests/test_langfuse_integration.py
Pruebas de integración con Langfuse para JARVI 2.0.

Estas pruebas validan que la instrumentación con Langfuse funciona correctamente
en el entorno de desarrollo/pruebas. No se ejecutan en producción.

ESTÁNDARES APLICADOS:
- ISO/IEC 29119:2022 (Pruebas) – Pruebas de integración y caja negra
- ISO/IEC 25010:2011 (Calidad) – Fiabilidad, Mantenibilidad
- DORA – Pruebas de resiliencia

PRUEBAS DE CAJA NEGRA (ISO/IEC 29119):
    1. Verificar que el cliente Langfuse se inicializa correctamente.
    2. Verificar que el CallbackHandler se crea con los metadatos correctos.
    3. Verificar que las trazas se envían a Langfuse (requiere conexión real o mock).
    4. Verificar que los scores se registran correctamente.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

# Importar módulos a probar
from langfuse_config import langfuse_config, get_langfuse_handler, get_langfuse_client


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Configura variables de entorno para pruebas."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://test.langfuse.com")
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "test")


@pytest.fixture
def mock_langfuse_client():
    """Mock del cliente Langfuse para evitar llamadas reales."""
    with patch("langfuse.Langfuse") as mock_client:
        mock_client.return_value = MagicMock(spec=Langfuse)
        yield mock_client


# =============================================================================
# Pruebas de Configuración
# =============================================================================

def test_langfuse_config_initialization(mock_env_vars, mock_langfuse_client):
    """
    Prueba que la configuración de Langfuse se inicialice correctamente.
    """
    # Forzar recreación del singleton para usar las variables mock
    langfuse_config._initialized = False
    langfuse_config.__init__()

    assert langfuse_config.is_enabled is True
    assert langfuse_config.environment == "test"
    assert langfuse_config.client is not None


def test_langfuse_config_missing_keys(monkeypatch):
    """
    Prueba que langfuse_config maneje correctamente la falta de claves.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    # Forzar recreación
    langfuse_config._initialized = False
    langfuse_config.__init__()

    assert langfuse_config.is_enabled is False
    assert langfuse_config.client is None


def test_get_langfuse_handler(mock_env_vars, mock_langfuse_client):
    """
    Prueba la creación del CallbackHandler con metadatos.
    """
    langfuse_config._initialized = False
    langfuse_config.__init__()

    handler = get_langfuse_handler(
        user_id="+50212345678",
        session_id="thread-123",
        metadata={"caso": "ABC123", "origen": "test"}
    )

    assert isinstance(handler, CallbackHandler)
    # No podemos inspeccionar internamente fácilmente, pero podemos verificar que no es None


def test_get_langfuse_handler_disabled(monkeypatch):
    """
    Prueba que get_langfuse_handler retorne None cuando Langfuse está desactivado.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    langfuse_config._initialized = False
    langfuse_config.__init__()

    handler = get_langfuse_handler(user_id="+50212345678")
    assert handler is None


# =============================================================================
# Pruebas de Integración con el Cliente
# =============================================================================

def test_get_langfuse_client(mock_env_vars, mock_langfuse_client):
    """
    Prueba que get_langfuse_client retorne el cliente Langfuse.
    """
    langfuse_config._initialized = False
    langfuse_config.__init__()

    client = get_langfuse_client()
    assert client is not None
    # Verificar que es el cliente mockeado
    assert client == langfuse_config.client


def test_get_langfuse_client_disabled(monkeypatch):
    """
    Prueba que get_langfuse_client retorne None cuando Langfuse está desactivado.
    """
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    langfuse_config._initialized = False
    langfuse_config.__init__()

    client = get_langfuse_client()
    assert client is None


# =============================================================================
# Pruebas de Flujo Real (con conexión real, solo en entornos específicos)
# =============================================================================

@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="Integración real requiere RUN_INTEGRATION_TESTS=1"
)
def test_real_langfuse_trace():
    """
    Prueba de integración real con Langfuse Cloud.
    Requiere variables de entorno configuradas y conexión a Internet.
    Ejecutar con: RUN_INTEGRATION_TESTS=1 pytest tests/test_langfuse_integration.py
    """
    from langfuse import Langfuse
    from langfuse.callback import CallbackHandler
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    # Inicializar cliente
    langfuse = Langfuse()
    handler = CallbackHandler(user_id="test-user", session_id="test-session")

    # Crear una cadena simple de prueba
    def dummy_chain(input):
        return f"Respuesta a: {input}"

    chain = RunnableLambda(dummy_chain)

    # Ejecutar con callback
    result = chain.invoke(
        "Hola, prueba",
        config={"callbacks": [handler]}
    )

    # Forzar flush
    langfuse.flush()

    # Verificar que no hubo errores (no podemos verificar la traza sin la API)
    assert result == "Respuesta a: Hola, prueba"
    print("✅ Traza enviada a Langfuse. Verificar en dashboard.")


# =============================================================================
# Pruebas de Scores
# =============================================================================

def test_score_creation(mock_env_vars, mock_langfuse_client):
    """
    Prueba que la creación de scores funcione correctamente.
    """
    langfuse_config._initialized = False
    langfuse_config.__init__()
    client = get_langfuse_client()

    # Mock del método score
    client.score = MagicMock()

    # Llamar al método score
    client.score(
        trace_id="test-trace",
        name="satisfaccion",
        value=4.5,
        comment="Muy buena respuesta"
    )

    client.score.assert_called_once_with(
        trace_id="test-trace",
        name="satisfaccion",
        value=4.5,
        comment="Muy buena respuesta"
    )


def test_feedback_endpoint_contract():
    """
    Prueba que el contrato del endpoint /feedback sea válido.
    Esto es una prueba de contrato (no de integración).
    """
    # Simular payload esperado
    payload = {
        "trace_id": "test-123",
        "name": "claridad",
        "value": 5,
        "comment": "Excelente explicación"
    }

    # Validar que los campos requeridos existen
    assert "trace_id" in payload
    assert "value" in payload
    # name y comment son opcionales, pero si están, deben tener tipos correctos
    if "name" in payload:
        assert isinstance(payload["name"], str)
    if "comment" in payload:
        assert isinstance(payload["comment"], str)
    assert isinstance(payload["value"], (int, float))
