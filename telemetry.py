import asyncio
import os
import json
import uuid
import logging
from contextvars import ContextVar
from typing import Optional, Any
from psycopg_pool import AsyncConnectionPool
from psycopg.conninfo import conninfo_to_dict

# Configuración de Logging conforme a ISO/IEC 26514
logger = logging.getLogger("jarvi.telemetry")

# Variables de contexto para propagar trace/span (Gobernanza de trazabilidad)
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("span_id", default="")
parent_span_id_var: ContextVar[str] = ContextVar("parent_span_id", default="")

# Cola para inserciones batch
_event_queue: asyncio.Queue = asyncio.Queue()
_pool: Optional[AsyncConnectionPool] = None

async def _get_pool():
    """Obtiene o crea un pool de conexiones limpio (Solución a ProgrammingError)."""
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL no configurada")
        
        # Limpiar la URL de parámetros no soportados por psycopg3 (ISO/IEC 25010 - Fiabilidad)
        params = conninfo_to_dict(db_url)
        params.pop('pool_size', None)
        
        _pool = AsyncConnectionPool(conninfo=params, min_size=1, max_size=10, open=True)
    return _pool

async def _batch_worker():
    """Consume eventos de la cola y los inserta en lotes con gestión de pool."""
    while True:
        batch = []
        batch.append(await _event_queue.get())
        try:
            while len(batch) < 100:
                batch.append(_event_queue.get_nowait())
        except asyncio.QueueEmpty:
            pass
        
        pool = await _get_pool()
        async with pool.connection() as conn:
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
                logger.error(f"Error en batch insert (Auditoría Forense): {e}")
        
        for _ in range(len(batch)):
            _event_queue.task_done()

async def log_telemetry_event(trace_id: str, span_id: str, parent_span_id: str,
                              layer: str, event_type: str, node_name: str = None,
                              latency_ms: int = None, severity: str = 'INFO',
                              error_code: str = None, cpu_percent: float = None,
                              memory_mb: float = None, dispatch_success: bool = None,
                              metadata: dict = None,
                              thread_id: str = None, run_id: str = None):
    """Agrega un evento a la cola de telemetría asegurando persistencia ACID."""
    if not hasattr(log_telemetry_event, "_started"):
        asyncio.create_task(_batch_worker())
        log_telemetry_event._started = True

    event = (
        trace_id, span_id, parent_span_id, thread_id, run_id,
        layer, node_name, event_type, latency_ms, severity, error_code,
        cpu_percent, memory_mb, dispatch_success, json.dumps(metadata or {})
    )
    await _event_queue.put(event)

def generate_trace_span():
    """Genera nuevos IDs de traza conforme al estándar de observabilidad JARVI 2.0."""
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    trace_id_var.set(trace_id)
    span_id_var.set(span_id)
    parent_span_id_var.set("")
    return trace_id, span_id
