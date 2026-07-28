"""
observability.py - Adaptador REST para Langfuse (sin SDK).
VERSIÓN 2.0.19 – Estable, compatible con Langfuse OSS V3.
"""
import os
import json
import base64
import uuid
import logging
import requests
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from urllib.parse import urljoin

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
# ADAPTADOR REST
# =============================================================================
class LangfuseRESTAdapter(ObservabilityPort):
    """Adaptador que usa la API REST de Langfuse (compatible con OSS)."""

    def __init__(self, public_key: str, secret_key: str, host: str):
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host.rstrip('/')
        self.auth_header = self._build_auth_header()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.auth_header,
            "Content-Type": "application/json"
        })
        logger.info(f"Langfuse REST adapter inicializado: {self.host}")

    def _build_auth_header(self) -> str:
        credentials = f"{self.public_key}:{self.secret_key}"
        b64 = base64.b64encode(credentials.encode()).decode()
        return f"Basic {b64}"

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = urljoin(self.host + '/', endpoint)
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en POST {endpoint}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Respuesta: {e.response.text}")
            raise

    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        payload = {
            "name": name,
            "userId": user_id,
            "sessionId": session_id,
            "metadata": metadata,
            "input": input_data,
            "public": False,
            "bookmarked": False
        }
        # Limpiar campos vacíos
        payload = {k: v for k, v in payload.items() if v is not None}
        data = self._post("api/public/traces", payload)
        trace_id = data.get("id")
        if not trace_id:
            logger.error(f"No se recibió ID de traza: {data}")
            raise RuntimeError("Langfuse no devolvió ID de traza")
        logger.info(f"Traza REST creada: {trace_id}")
        return trace_id

    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        payload = {
            "traceId": trace_id,
            "name": name,
            "model": model,
            "input": input_data,
            "output": output_data,
            "usage": {
                "input": usage.get("input", 0),
                "output": usage.get("output", 0),
                "total": usage.get("total", 0),
                "unit": "TOKENS"
            },
            "startTime": start_time.isoformat(),
            "endTime": end_time.isoformat(),
            "metadata": metadata
        }
        self._post("api/public/observations", payload)
        logger.info(f"Observación GENERATION creada para trace {trace_id}")

    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        payload = {
            "traceId": trace_id,
            "name": name,
            "value": value,
            "dataType": data_type,
            "comment": comment
        }
        self._post("api/public/scores", payload)
        logger.info(f"Score '{name}' = {value} registrado para trace {trace_id}")

    def flush(self) -> None:
        # En REST no hay flush; todas las llamadas son síncronas.
        logger.debug("Flush llamado (no-op para REST)")
