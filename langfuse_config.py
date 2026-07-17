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
        logger.info("Iniciando verificación de Langfuse...")
        try:
            from langfuse import Langfuse
            logger.info("Módulo langfuse importado correctamente.")
            if not self._public_key or not self._secret_key:
                logger.error("Langfuse credenciales incompletas. Public Key o Secret Key faltantes.")
                raise ValueError("Faltan credenciales de Langfuse")
            logger.info(f"Credenciales encontradas. Host: {self._host}")
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host
            )
            self._is_enabled = True
            logger.info(f"Langfuse cliente inicializado correctamente. Host: {self._host}")
        except ImportError as e:
            logger.error(f"ImportError al importar langfuse: {e}")
            raise  # Relanza para que el contenedor falle y veamos el error
        except Exception as e:
            logger.error(f"Error al inicializar Langfuse: {e}", exc_info=True)
            raise  # Relanza para que el contenedor falle y veamos el error

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
            logger.debug("Langfuse no disponible: no se crea CallbackHandler")
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
        except ImportError as e:
            logger.error(f"No se pudo importar CallbackHandler: {e}")
            return None
        except Exception as e:
            logger.error(f"Error al crear CallbackHandler: {e}")
            return None


langfuse_config = LangfuseConfig()


def get_langfuse_handler(user_id=None, session_id=None, metadata=None):
    return langfuse_config.get_handler(user_id, session_id, metadata)


def get_langfuse_client():
    return langfuse_config.client
