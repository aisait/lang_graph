"""
observability.py - Adaptador REST para Langfuse OSS (v3.224.2)
VERSIÓN 2.0.20 – Compatible con OSS: usa PUT /traces/{id} y POST /traces/{id}/observations
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
# ADAPTADOR REST – COMPATIBLE CON OSS
# =============================================================================
class LangfuseRESTAdapter(ObservabilityPort):
    """
    Adaptador REST que funciona con la versión OSS de Langfuse.
    Estrategia:
      1. POST /api/public/traces -> crea traza (ya funciona)
      2. PUT /api/public/traces/{traceId} -> actualiza traza con output y usage
      3. Si falla, intenta POST /api/public/traces/{traceId}/observations
      4. POST /api/public/scores -> crea scores (ya funciona)
    """

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

    def _request(self, method: str, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = urljoin(self.host + '/', endpoint)
        try:
            resp = self.session.request(method, url, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en {method} {endpoint}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Status: {e.response.status_code} - Respuesta: {e.response.text[:500]}")
            raise

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('POST', endpoint, payload)

    def _put(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('PUT', endpoint, payload)

    # --------------------------------------------------------------------------
    # 1. CREAR TRAZA
    # --------------------------------------------------------------------------
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
        payload = {k: v for k, v in payload.items() if v is not None}
        data = self._post("api/public/traces", payload)
        trace_id = data.get("id")
        if not trace_id:
            raise RuntimeError(f"Langfuse no devolvió ID de traza: {data}")
        logger.info(f"Traza REST creada: {trace_id}")
        return trace_id

    # --------------------------------------------------------------------------
    # 2. CREAR OBSERVACIÓN (GENERATION) – ESTRATEGIA OSS
    # --------------------------------------------------------------------------
    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        # Construir payload común
        payload = {
            "output": output_data,
            "usage": {
                "input": usage.get("input", 0),
                "output": usage.get("output", 0),
                "total": usage.get("total", 0),
                "unit": "TOKENS"
            },
            "metadata": metadata
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        # ---- Estrategia 1: PUT /api/public/traces/{traceId} ----
        # (Algunas versiones OSS permiten actualizar la traza con output)
        try:
            self._put(f"api/public/traces/{trace_id}", payload)
            logger.info(f"✅ Traza actualizada con output para {trace_id}")
            return
        except requests.exceptions.RequestException as e:
            logger.warning(f"PUT a /traces falló: {e}. Intentando alternativa...")

        # ---- Estrategia 2: POST /api/public/traces/{traceId}/observations ----
        obs_payload = {
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
        obs_payload = {k: v for k, v in obs_payload.items() if v is not None}
        try:
            self._post(f"api/public/traces/{trace_id}/observations", obs_payload)
            logger.info(f"✅ Observación creada para trace {trace_id}")
            return
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ ERROR: No se pudo crear observación para {trace_id}: {e}")
            # No lanzamos excepción para no interrumpir el flujo, pero queda registrado

    # --------------------------------------------------------------------------
    # 3. CREAR SCORE
    # --------------------------------------------------------------------------
    def create_score(self, trace_id: str, name: str, value: float,
                     data_type: str = "NUMERIC", comment: Optional[str] = None) -> None:
        payload = {
            "traceId": trace_id,
            "name": name,
            "value": value,
            "dataType": data_type,
            "comment": comment
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        self._post("api/public/scores", payload)
        logger.info(f"Score '{name}' = {value} registrado para trace {trace_id}")

    # --------------------------------------------------------------------------
    # 4. FLUSH (no-op para REST)
    # --------------------------------------------------------------------------
    def flush(self) -> None:
        logger.debug("Flush llamado (no-op para REST)")


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
