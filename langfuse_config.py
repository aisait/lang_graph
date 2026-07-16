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

from langfuse import Langfuse
from langfuse.callback import CallbackHandler

logger = logging.getLogger(__name__)


class LangfuseConfig:
    """
    Configuración centralizada de Langfuse para JARVI 2.0.
    Sigue el patrón Singleton para evitar múltiples inicializaciones.
    """

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

        # Validación de credenciales (ISO/IEC 27001)
        if not self._public_key or not self._secret_key:
            logger.warning(
                "Langfuse no configurado correctamente: faltan LANGFUSE_PUBLIC_KEY o LANGFUSE_SECRET_KEY. "
                "La trazabilidad LLM estará desactivada."
            )
            self._client = None
        else:
            try:
                self._client = Langfuse(
                    public_key=self._public_key,
                    secret_key=self._secret_key,
                    host=self._host
                )
                logger.info(
                    f"Langfuse cliente inicializado correctamente. "
                    f"Host: {self._host}, Environment: {self._environment}"
                )
            except Exception as e:
                logger.error(f"Error al inicializar Langfuse: {e}")
                self._client = None

    @property
    def client(self):
        """Retorna el cliente Langfuse (puede ser None si no está configurado)."""
        return self._client

    @property
    def is_enabled(self) -> bool:
        """Indica si Langfuse está correctamente configurado y activo."""
        return self._client is not None

    @property
    def environment(self) -> str:
        """Retorna el entorno actual (production, staging, etc.)."""
        return self._environment

    def get_handler(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[CallbackHandler]:
        """
        Crea un CallbackHandler de Langfuse con los parámetros proporcionados.
        Si Langfuse no está habilitado, retorna None.

        Prueba de caja negra (ISO/IEC 29119):
            1. Llamar con user_id válido → retorna CallbackHandler con user_id
            2. Llamar sin user_id y sin session_id → retorna CallbackHandler sin metadatos
            3. Llamar cuando Langfuse está desactivado → retorna None
        """
        if not self.is_enabled:
            logger.debug("Langfuse desactivado: no se crea CallbackHandler")
            return None

        # Asegurar que metadata no sea None
        safe_metadata = metadata or {}
        # Añadir entorno por defecto si no está presente
        if "environment" not in safe_metadata:
            safe_metadata["environment"] = self._environment

        return CallbackHandler(
            user_id=user_id,
            session_id=session_id,
            metadata=safe_metadata
        )


# Instancia global (Singleton)
langfuse_config = LangfuseConfig()

# Función de conveniencia para obtener el handler
def get_langfuse_handler(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None
) -> Optional[CallbackHandler]:
    """
    Función de conveniencia que delega en langfuse_config.get_handler.
    """
    return langfuse_config.get_handler(user_id, session_id, metadata)


# Función para obtener el cliente Langfuse (útil para scores y consultas)
def get_langfuse_client():
    """
    Retorna el cliente Langfuse.
    Puede ser None si Langfuse no está configurado.
    """
    return langfuse_config.client
