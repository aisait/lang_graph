"""
langfuse_cfg.py
Configuración centralizada de Langfuse para JARVI 2.0.
Renombrado para forzar reconstrucción de caché en Railway.
"""

import os
import logging
from typing import Optional

print("=== [LANGFUSE] CARGANDO MÓDULO langfuse_cfg.py ===")

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
        print("=== [LANGFUSE] Entrando a __init__ ===")
        self._public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        self._secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self._host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self._environment = os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
        self._client = None
        self._is_enabled = False
        self._check_availability()

    def _check_availability(self):
        print("=== [LANGFUSE] Iniciando verificación de disponibilidad ===")
        try:
            from langfuse import Langfuse
            print("=== [LANGFUSE] Módulo langfuse importado ===")
            if not self._public_key or not self._secret_key:
                raise ValueError("Faltan credenciales de Langfuse")
            print(f"=== [LANGFUSE] Credenciales OK. Host: {self._host}")
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host
            )
            self._is_enabled = True
            print(f"=== [LANGFUSE] Cliente inicializado correctamente. Host: {self._host}")
        except Exception as e:
            print(f"=== [LANGFUSE] ERROR: {e}")
            raise  # Para que el contenedor falle y veamos el error

    @property
    def client(self):
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
            print("=== [LANGFUSE] Langfuse no disponible, handler no creado ===")
            return None
        try:
            from langfuse.callback import CallbackHandler
            safe_metadata = metadata or {}
            if "environment" not in safe_metadata:
                safe_metadata["environment"] = self._environment
            return CallbackHandler(
                user_id=user_id,
                session_id=session_id,
                metadata=safe_metadata
            )
        except Exception as e:
            print(f"=== [LANGFUSE] Error al crear CallbackHandler: {e}")
            return None


langfuse_config = LangfuseConfig()


def get_langfuse_handler(user_id=None, session_id=None, metadata=None):
    return langfuse_config.get_handler(user_id, session_id, metadata)


def get_langfuse_client():
    return langfuse_config.client
