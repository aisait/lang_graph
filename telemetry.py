import asyncio
import os
import json
import uuid
import time
import psutil
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# Cliente asíncrono de PostgreSQL (reutilizar conexión de la API o crear una dedicada)
import psycopg
from psycopg import AsyncConnection

logger = logging.getLogger("jarvi.telemetry")

# Variables de contexto para propagar trace/span
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("span_id", default="")
parent_span_id_var: ContextVar[str] = ContextVar("parent_span_id", default="")

# Cola para inserciones batch
_event_queue: asyncio.Queue = asyncio.Queue()

# Worker flag
_worker_started = False

async def _batch_worker():
    """Consume eventos de la cola y los inserta en lotes."""
    global _worker_started
    _worker_started = True
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL no disponible para telemetría")
        return
    async with await AsyncConnection.connect(db_url) as conn:
        while True:
            batch = []
            # Esperar primer evento
            batch.append(await _event_queue.get())
            # Recoger más eventos sin bloquear
            try:
                while len(batch) < 100:
                    batch.append(_event_queue.get_nowait())
            except asyncio.QueueEmpty:
                pass
            # Insertar lote
            try:
                async with conn.transaction():
                    async with conn.cursor() as cur:
                        await cur.executemany(
                            """INSERT INTO telemetry_events 
                            (trace_id, span_id, parent_span_id, thread_id, run_id, layer, node_name,
                             event_type, latency_ms, severity, error_code, cpu_percent, memory_mb,
                             dispatch_success, metadata)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            batch
                        )
            except Exception as e:
                logger.error(f"Error en batch insert: {e}")

async def log_telemetry_event(trace_id: str, span_id: str, parent_span_id: str,
                              layer: str, event_type: str, node_name: str = None,
                              latency_ms: int = None, severity: str = 'INFO',
                              error_code: str = None, cpu_percent: float = None,
                              memory_mb: float = None, dispatch_success: bool = None,
                              metadata: dict = None,
                              thread_id: str = None, run_id: str = None):
    """Agrega un evento a la cola de telemetría."""
    global _worker_started
    if not _worker_started:
        # Iniciar worker en el event loop actual
        asyncio.create_task(_batch_worker())

    event = (
        trace_id, span_id, parent_span_id, thread_id, run_id,
        layer, node_name, event_type, latency_ms, severity, error_code,
        cpu_percent, memory_mb, dispatch_success, json.dumps(metadata or {})
    )
    await _event_queue.put(event)

def generate_trace_span():
    """Genera nuevos trace_id y span_id y los establece en contexto."""
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    trace_id_var.set(trace_id)
    span_id_var.set(span_id)
    parent_span_id_var.set("")
    return trace_id, span_id
