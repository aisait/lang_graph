"""
observability.py - Adaptador REST con INGESTION API para Langfuse OSS
VERSIÓN 2.0.26 – ESTABLE: solo trace-create y observation-create, sin trace-update
"""
import os
import json
import base64
import uuid
import logging
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
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
# ADAPTADOR INGESTION API (ESTABLE)
# =============================================================================
class LangfuseIngestionAdapter(ObservabilityPort):
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
        self._pending_events = []
        logger.info(f"Langfuse Ingestion adapter inicializado: {self.host}")

    def _build_auth_header(self) -> str:
        credentials = f"{self.public_key}:{self.secret_key}"
        b64 = base64.b64encode(credentials.encode()).decode()
        return f"Basic {b64}"

    def _send_batch(self, events: list) -> bool:
        if not events:
            return True
        payload = {"batch": events}
        url = urljoin(self.host + '/', "api/public/ingestion")
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"✅ Ingestion batch enviado: {len(events)} eventos")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en ingestion: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Status: {e.response.status_code} - Respuesta: {e.response.text[:500]}")
            return False

    # --------------------------------------------------------------------------
    # 1. CREAR TRAZA (sin tags ni output)
    # --------------------------------------------------------------------------
    def create_trace(self, name: str, user_id: str, session_id: str,
                     metadata: Dict[str, Any], input_data: Dict[str, Any]) -> str:
        trace_id = str(uuid.uuid4())
        body = {
            "id": trace_id,
            "name": name,
            "userId": user_id,
            "sessionId": session_id,
            "metadata": metadata,
            "input": input_data,
            "public": False,
            "bookmarked": False
        }
        body = {k: v for k, v in body.items() if v is not None}

        event = {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "body": body
        }
        self._pending_events.append(event)
        logger.info(f"Traza en cola para ingestion: {trace_id}")
        return trace_id

    # --------------------------------------------------------------------------
    # 2. CREAR OBSERVACIÓN (GENERATION)
    # --------------------------------------------------------------------------
    def create_generation(self, trace_id: str, name: str, model: str,
                          input_data: Dict[str, Any], output_data: Dict[str, Any],
                          usage: Dict[str, int], start_time: datetime,
                          end_time: datetime, metadata: Dict[str, Any]) -> None:
        event = {
            "id": str(uuid.uuid4()),
            "type": "observation-create",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "body": {
                "id": str(uuid.uuid4()),
                "traceId": trace_id,
                "name": name,
                "type": "GENERATION",
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
        }
        event["body"] = {k: v for k, v in event["body"].items() if v is not None}
        self._pending_events.append(event)
        logger.info(f"Observación en cola para ingestion (trace {trace_id})")

    # --------------------------------------------------------------------------
    # 3. CREAR SCORE (POST /api/public/scores)
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
        url = urljoin(self.host + '/', "api/public/scores")
        try:
            self.session.post(url, json=payload, timeout=10).raise_for_status()
            logger.info(f"Score '{name}' = {value} registrado para trace {trace_id}")
        except Exception as e:
            logger.error(f"Error al crear score: {e}")

    # --------------------------------------------------------------------------
    # 4. FLUSH (envía el batch completo y limpia)
    # --------------------------------------------------------------------------
    def flush(self) -> None:
        if not self._pending_events:
            logger.debug("No hay eventos pendientes para flush")
            return

        sent = self._send_batch(self._pending_events)
        if sent:
            self._pending_events.clear()
            logger.info("✅ Batch enviado y cola vaciada")
        else:
            logger.error("Falló el envío del batch. Los eventos se mantienen en cola.")


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
