"""
db_client.py - Cliente de base de datos con reintentos y manejo de errores.
VERSIÓN 2.0.27 – Soporte para thread_id como texto (VARCHAR) o conversión a UUID.
"""
import os
import json
import asyncio
import hashlib
import uuid
import asyncpg
import logging
from typing import Optional, List, Dict, Any
from agent_graph import normalizar_contacto

logger = logging.getLogger("jarvi.db")

def thread_id_to_uuid(thread_id: str) -> str:
    """Convierte cualquier string a un UUID válido de forma determinista."""
    if not thread_id:
        return str(uuid.uuid4())
    try:
        uuid.UUID(thread_id)
        return thread_id
    except ValueError:
        hash_hex = hashlib.sha256(thread_id.encode()).hexdigest()
        return str(uuid.UUID(hex=hash_hex[:32]))

def get_bi_db_url() -> str:
    return os.getenv("BI_DATABASE_URL")

def get_ctfom_db_url() -> str:
    return os.getenv("CTFOM_DATABASE_URL")

async def get_db_connection(db_url: str, retries=3, delay=2):
    for attempt in range(retries):
        try:
            return await asyncpg.connect(db_url)
        except Exception as e:
            logger.warning(f"Intento {attempt+1} de conexión a DB falló: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(delay * (attempt + 1))

async def actualizar_thread(
    thread_id: str,
    nombre: str,
    whatsapp: str,
    email: Optional[str] = None,
    productos: Optional[List[str]] = None,
    vendedor: Optional[str] = None,
    trace_id: Optional[str] = None,
    cumulative_cost: Optional[float] = None,
    metadata_adicional: Optional[Dict[str, Any]] = None
) -> bool:
    conn = None
    try:
        _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
        db_url = get_bi_db_url()
        if not db_url:
            logger.error("BI_DATABASE_URL no configurada")
            return False
        conn = await get_db_connection(db_url)

        # La BD ahora acepta texto; convertimos a UUID solo si es necesario
        thread_id_uuid = thread_id_to_uuid(thread_id)

        if metadata_adicional is None:
            metadata_adicional = {}
        if not isinstance(metadata_adicional, dict):
            logger.error(f"metadata_adicional no es dict: {type(metadata_adicional)}")
            metadata_adicional = {}

        metadata = {
            "email": email,
            "productos": productos or [],
            "vendedor": vendedor,
            "trace_id": trace_id,
        }
        metadata.update(metadata_adicional)

        if cumulative_cost is not None:
            row = await conn.fetchrow(
                "SELECT metadata FROM threads WHERE thread_id = $1",
                thread_id_uuid
            )
            old_meta = row["metadata"] if row else {}
            if isinstance(old_meta, str):
                try:
                    old_meta = json.loads(old_meta)
                except:
                    old_meta = {}
            old_cost = old_meta.get("cumulative_cost", 0.0)
            metadata["cumulative_cost"] = old_cost + cumulative_cost
        else:
            if "cumulative_cost" not in metadata:
                row = await conn.fetchrow(
                    "SELECT metadata FROM threads WHERE thread_id = $1",
                    thread_id_uuid
                )
                if row:
                    old_meta = row["metadata"] if row else {}
                    if isinstance(old_meta, str):
                        try:
                            old_meta = json.loads(old_meta)
                        except:
                            old_meta = {}
                    metadata["cumulative_cost"] = old_meta.get("cumulative_cost", 0.0)
                else:
                    metadata["cumulative_cost"] = 0.0

        await conn.execute(
            """
            INSERT INTO threads (thread_id, nombre_cliente, whatsapp_id, metadata)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (thread_id) DO UPDATE
            SET nombre_cliente = EXCLUDED.nombre_cliente,
                whatsapp_id = EXCLUDED.whatsapp_id,
                metadata = EXCLUDED.metadata
            """,
            thread_id_uuid,
            nombre,
            whatsapp_norm,
            json.dumps(metadata)
        )

        logger.info(f"Thread actualizado (BI): {thread_id} - {nombre} ({whatsapp_norm})")
        return True
    except Exception as e:
        logger.error(f"Error al actualizar thread: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def registrar_evento_auditoria(
    thread_id: str,
    trace_id: str,
    event_type: str,
    source: str,
    payload: Dict[str, Any],
    langsmith_run_id: Optional[str] = None
) -> bool:
    conn = None
    try:
        db_url = get_ctfom_db_url()
        if not db_url:
            logger.error("CTFOM_DATABASE_URL no configurada")
            return False
        conn = await get_db_connection(db_url)
        await conn.execute(
            """
            INSERT INTO audit_events (
                thread_id, timestamp, event_type, source,
                system_snapshot, request_payload, langsmith_run_id
            )
            VALUES ($1, NOW(), $2, $3, $4, $5, $6)
            """,
            thread_id,
            event_type,
            source,
            json.dumps({"trace_id": trace_id}),
            json.dumps(payload),
            langsmith_run_id
        )
        return True
    except Exception as e:
        logger.error(f"Error al registrar evento: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def acumular_costo_thread(thread_id: str, costo: float) -> bool:
    conn = None
    try:
        db_url = get_bi_db_url()
        if not db_url:
            logger.error("BI_DATABASE_URL no configurada")
            return False
        conn = await get_db_connection(db_url)
        thread_id_uuid = thread_id_to_uuid(thread_id)
        await conn.execute(
            """
            UPDATE threads
            SET metadata = jsonb_set(
                metadata,
                '{cumulative_cost}',
                to_jsonb(COALESCE((metadata->>'cumulative_cost')::numeric, 0) + $1)
            )
            WHERE thread_id = $2
            """,
            costo,
            thread_id_uuid
        )
        return True
    except Exception as e:
        logger.error(f"Error al acumular costo: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def obtener_costo_acumulado(thread_id: str) -> float:
    conn = None
    try:
        db_url = get_bi_db_url()
        if not db_url:
            logger.error("BI_DATABASE_URL no configurada")
            return 0.0
        conn = await get_db_connection(db_url)
        thread_id_uuid = thread_id_to_uuid(thread_id)
        row = await conn.fetchrow(
            "SELECT metadata->>'cumulative_cost' as cost FROM threads WHERE thread_id = $1",
            thread_id_uuid
        )
        return float(row["cost"]) if row and row["cost"] else 0.0
    except Exception as e:
        logger.error(f"Error al obtener costo acumulado: {e}")
        return 0.0
    finally:
        if conn:
            await conn.close()
