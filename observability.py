"""
observability.py - Puertos y adaptadores para la instrumentación con Langfuse.
VERSIÓN 2.0.18 – Arquitectura limpia, desacoplamiento del SDK.
"""
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime
import logging

# Intentar importar el SDK, pero con manejo de error si no está instalado
try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

logger = logging.getLogger(__name__)

# =============================================================================
# INTERFAZ (PUERTO)
# =============================================================================
class ObservabilityPort(ABC):
    """Puerto de observabilidad para el dominio de negocio."""

    @abstractmethod
    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        """Crea una traza y retorna su ID."""
        pass

    @abstractmethod
    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        """Crea una observación de tipo GENERATION asociada a una traza."""
        pass

    @abstractmethod
    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        """Crea un score asociado a una traza."""
        pass

    @abstractmethod
    def flush(self) -> None:
        """Garantiza el envío de todos los eventos pendientes."""
        pass


# =============================================================================
# ADAPTADOR CON SDK DE LANGFUSE
# =============================================================================
class LangfuseSDKAdapter(ObservabilityPort):
    """Implementación del puerto de observabilidad usando el SDK de Langfuse."""

    def __init__(self, public_key: str, secret_key: str, host: str):
        if Langfuse is None:
            raise RuntimeError("Langfuse SDK no está instalado. Ejecute: pip install langfuse>=3.0.0")

        self.client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        self._check_version()

    def _check_version(self):
        """Verifica que el SDK tenga el método 'trace' (versión >= 3.0)."""
        if not hasattr(self.client, 'trace'):
            raise RuntimeError(
                "Versión del SDK de Langfuse demasiado antigua. "
                "Actualice a >= 3.0.0 (ej. pip install langfuse>=3.0.0)"
            )
        logger.info("Langfuse SDK versión compatible (>= 3.0.0)")

    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        trace = self.client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
            input=input_data
        )
        return trace.id

    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        # Obtener la traza existente
        trace = self.client.get_trace(trace_id)
        if not trace:
            logger.warning(f"No se encontró la traza {trace_id} para crear generación")
            return
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

    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        self.client.score(
            trace_id=trace_id,
            name=name,
            value=value,
            data_type=data_type,
            comment=comment
        )

    def flush(self) -> None:
        self.client.flush()
