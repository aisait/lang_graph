"""
db_client.py
═══════════════════════════════════════════════════════════════════════
Cliente de base de datos para BI y CTFOM.
Extiende la funcionalidad para almacenar cumulative_cost en threads (BI).

Cumple con ISO/IEC 25010 (mantenibilidad) y DORA (auditabilidad).

Pruebas de caja negra (ISO/IEC 29119):
    BC‑T08: Verificar que cumulative_cost se actualice en threads.metadata.
"""
import os
import json
import asyncpg
import logging
from typing import Optional, List, Dict, Any
from agent_graph import normalizar_contacto

logger = logging.getLogger("jarvi.db")

def get_bi_db_url() -> str:
    return os.getenv("BI_DATABASE_URL")

def get_ctfom_db_url() -> str:
    return os.getenv("CTFOM_DATABASE_URL")

async def get_db_connection(db_url: str):
    return await asyncpg.connect(db_url)

async def actualizar_thread(
    thread_id: str,
    nombre: str,
    whatsapp: str,
    email: Optional[str] = None,
    productos: Optional[List[str]] = None,
    vendedor: Optional[str] = None,
    trace_id: Optional[str] = None,
    cumulative_cost: Optional[float] = None  # NUEVO: costo acumulado
) -> bool:
    """
    Actualiza o inserta un thread en BI, acumulando costos de LLM.
    """
    conn = None
    try:
        _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
        conn = await get_db_connection(get_bi_db_url())
        metadata = {
            "email": email,
            "productos": productos or [],
            "vendedor": vendedor,
            "trace_id": trace_id,
        }
        existing = await conn.fetchrow(
            "SELECT thread_id, metadata FROM threads WHERE whatsapp_id = $1",
            whatsapp_norm
        )
        if existing:
            old_meta = existing["metadata"] or {}
            # Acumular costo
            old_cost = old_meta.get("cumulative_cost", 0.0)
            new_cost = old_cost + (cumulative_cost or 0.0)
            metadata["cumulative_cost"] = new_cost
            await conn.execute(
                """
                UPDATE threads
                SET nombre_cliente = $1, metadata = $2
                WHERE whatsapp_id = $3
                """,
                nombre,
                json.dumps(metadata),
                whatsapp_norm
            )
        else:
            metadata["cumulative_cost"] = cumulative_cost or 0.0
            await conn.execute(
                """
                INSERT INTO threads (thread_id, nombre_cliente, whatsapp_id, metadata)
                VALUES ($1, $2, $3, $4)
                """,
                thread_id,
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
    """Registra un evento de auditoría en CTFOM."""
    conn = None
    try:
        conn = await get_db_connection(get_ctfom_db_url())
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
    """Función auxiliar para acumular costo en threads (mantenida por compatibilidad)."""
    conn = None
    try:
        conn = await get_db_connection(get_bi_db_url())
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
            thread_id
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
        conn = await get_db_connection(get_bi_db_url())
        row = await conn.fetchrow(
            "SELECT metadata->>'cumulative_cost' as cost FROM threads WHERE thread_id = $1",
            thread_id
        )
        return float(row["cost"]) if row and row["cost"] else 0.0
    except Exception:
        return 0.0
    finally:
        if conn:
            await conn.close()
