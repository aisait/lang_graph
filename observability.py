"""
observability.py - Adaptador SDK para Langfuse (versión 3.9.0)
VERSIÓN 2.0.22 – Sintaxis correcta: client.trace() + trace.generation()
Basado en investigación científica y documentación oficial.
"""
import os
import uuid
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from abc import ABC, abstractmethod

# Intentar importar el SDK
try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

logger = logging.getLogger(__name__)

# =============================================================================
# INTERFAZ (PUERTO)
# =============================================================================
class ObservabilityPort(ABC):
    @abstractmethod
    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def flush(self) -> None:
        pass


# =============================================================================
# ADAPTADOR SDK (NATIVO) – SINTAXIS CORRECTA
# =============================================================================
class LangfuseSDKAdapter(ObservabilityPort):
    """
    Usa el SDK oficial de Langfuse (versión >= 3.0.0).
    IMPORTANTE: 
      - client.trace() retorna un objeto trace con método .generation()
      - NO usar client.get_trace() (no existe en v3+)
      - NO usar REST para actualizaciones (no soportado en OSS)
    """

    def __init__(self, public_key: str, secret_key: str, host: str):
        if Langfuse is None:
            raise RuntimeError("Langfuse SDK no está instalado. Ejecute: pip install langfuse>=3.0.0")
        self.client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        self._traces_cache = {}  # Guarda objetos trace para reutilizar
        self._check_version()
        logger.info("Langfuse SDK adapter inicializado correctamente")

    def _check_version(self):
        """Verifica que el SDK tenga el método 'trace' (versión >= 3.0)."""
        if not hasattr(self.client, 'trace'):
            raise RuntimeError(
                "Versión del SDK de Langfuse demasiado antigua. "
                "Actualice a >= 3.0.0 (ej. pip install langfuse>=3.0.0)"
            )
        logger.info("Langfuse SDK versión compatible (>= 3.0.0)")

    # --------------------------------------------------------------------------
    # 1. CREAR TRAZA
    # --------------------------------------------------------------------------
    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        trace = self.client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
            input=input_data
        )
        self._traces_cache[trace.id] = trace
        logger.info(f"Traza SDK creada: {trace.id}")
        return trace.id

    # --------------------------------------------------------------------------
    # 2. CREAR GENERACIÓN (OBSERVACIÓN)
    # --------------------------------------------------------------------------
    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        # Obtener el objeto trace del caché
        trace = self._traces_cache.get(trace_id)
        if not trace:
            # Si no está en caché, no podemos obtenerlo (get_trace no existe)
            logger.error(f"No se encontró la traza {trace_id} en caché. No se puede crear generación.")
            return

        try:
            trace.generation(
                name=name,
                model=model,
                input=input_data,
                output=output_data,
                usage=usage,
                start_time=start_time,
                end_time=end_time,
                metadata=metadata
            )
            logger.info(f"✅ Generación creada para trace {trace_id}")
        except Exception as e:
            logger.error(f"Error al crear generación: {e}")

    # --------------------------------------------------------------------------
    # 3. CREAR SCORE
    # --------------------------------------------------------------------------
    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        try:
            self.client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                data_type=data_type,
                comment=comment
            )
            logger.info(f"Score '{name}' = {value} registrado para trace {trace_id}")
        except Exception as e:
            logger.error(f"Error al crear score: {e}")

    # --------------------------------------------------------------------------
    # 4. FLUSH
    # --------------------------------------------------------------------------
    def flush(self) -> None:
        try:
            self.client.flush()
            logger.debug("Flush SDK completado")
        except Exception as e:
            logger.error(f"Error en flush: {e}")


# =============================================================================
# ADAPTADOR NULO (FALLBACK)
# =============================================================================
class NullObservabilityAdapter(ObservabilityPort):
    def create_trace(self, *args, **kwargs):
        logger.warning("NullObservabilityAdapter: create_trace (no-op)")
        return str(uuid.uuid4())

    def create_generation(self, *args, **kwargs):
        logger.warning("NullObservabilityAdapter: create_generation (no-op)")

    def create_score(self, *args, **kwargs):
        logger.warning("NullObservabilityAdapter: create_score (no-op)")

    def flush(self):
        pass
