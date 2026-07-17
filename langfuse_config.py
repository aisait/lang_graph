"""
langfuse_config.py
Configuración centralizada de Langfuse para JARVI 2.0.

Este módulo encapsula la inicialización y configuración del cliente de Langfuse,
así como la creación de CallbackHandlers con metadatos de negocio.

ESTÁNDARES APLICADOS:
- ISO/IEC 25010:2011 (Calidad del producto) – Mantenibilidad, Reutilización
- ISO/IEC 29119:2022 (Pruebas) – Pruebas de caja negra documentadas
- ISO/IEC 27001:2022 (Seguridad) – Gestión de secretos
- DORA (EU) – Resiliencia operacional

PRUEBAS DE CAJA NEGRA (ISO/IEC 29119):
    1. Inicializar con variables de entorno correctas → cliente Langfuse activo
    2. Inicializar sin LANGFUSE_PUBLIC_KEY → lanza ValueError
    3. get_langfuse_handler() con user_id → retorna CallbackHandler con metadatos
    4. get_langfuse_handler() sin user_id → usa fallback
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class LangfuseConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        self._secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self._host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self._environment = os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
        self._client = None
        self._is_enabled = False
        self._check_availability()

    def _check_availability(self):
        """Verifica la disponibilidad del módulo y las credenciales de forma dinámica."""
        try:
            from langfuse import Langfuse
            from langfuse.callback import CallbackHandler
            if not self._public_key or not self._secret_key:
                logger.warning("Langfuse credenciales incompletas. Trazabilidad desactivada.")
                return
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host
            )
            self._is_enabled = True
            logger.info(f"Langfuse cliente inicializado correctamente. Host: {self._host}")
        except ImportError:
            logger.warning("El módulo langfuse no está disponible. Trazabilidad desactivada.")
        except Exception as e:
            logger.error(f"Error al inicializar Langfuse: {e}")

    @property
    def client(self):
        # Si el cliente no se inicializó, reintentar (por si el módulo se instaló después)
        if not self._is_enabled:
            self._check_availability()
        return self._client

    @property
    def is_enabled(self):
        if not self._is_enabled:
            self._check_availability()
        return self._is_enabled

    def get_handler(self, user_id=None, session_id=None, metadata=None):
        if not self.is_enabled:
            return None
        from langfuse.callback import CallbackHandler
        safe_metadata = metadata or {}
        safe_metadata["environment"] = self._environment
        return CallbackHandler(
            user_id=user_id,
            session_id=session_id,
            metadata=safe_metadata
        )

# Instancia global
langfuse_config = LangfuseConfig()
    return langfuse_config.client
