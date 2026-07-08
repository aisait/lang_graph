"""
db_client.py
Cliente de base de datos para operaciones CRUD sobre threads, audit_events y telemetry_events.
Cumple con ISO/IEC 25010 (Fiabilidad) y 29119 (Pruebas).
"""
import os
import json
import asyncpg
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("jarvi.db")

async def get_db_connection():
    """Obtiene una conexión a la base de datos PostgreSQL."""
    return await asyncpg.connect(os.getenv("DATABASE_URL"))

async def actualizar_thread(
    thread_id: str,
    nombre: str,
    whatsapp: str,
    email: Optional[str] = None,
    productos: Optional[List[str]] = None,
    vendedor: Optional[str] = None,
    trace_id: Optional[str] = None
) -> bool:
    """
    Inserta o actualiza la tabla threads con los datos del cliente.
    Retorna True si se actualizó correctamente, False en caso contrario.
    """
    conn = None
    try:
        conn = await get_db_connection()
        # Normalizar WhatsApp
        from agent_graph import normalizar_contacto
        _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
        
        # Verificar si existe por whatsapp_id
        existing = await conn.fetchrow(
            "SELECT thread_id, metadata FROM threads WHERE whatsapp_id = $1",
            whatsapp_norm
        )
        
        metadata = {
            "email": email,
            "productos": productos or [],
            "vendedor": vendedor,
            "trace_id": trace_id
        }
        
        if existing:
            # Actualizar
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
            logger.info(f"Thread actualizado: {thread_id} - {nombre} ({whatsapp_norm})")
        else:
            # Insertar
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
            logger.info(f"Nuevo thread creado: {thread_id} - {nombre} ({whatsapp_norm})")
        return True
    except Exception as e:
        logger.error(f"Error al actualizar thread: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def obtener_thread_por_whatsapp(whatsapp: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene los datos del cliente a partir de su número de WhatsApp normalizado.
    """
    conn = None
    try:
        conn = await get_db_connection()
        from agent_graph import normalizar_contacto
        _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
        row = await conn.fetchrow(
            "SELECT thread_id, nombre_cliente, whatsapp_id, metadata FROM threads WHERE whatsapp_id = $1",
            whatsapp_norm
        )
        if row:
            return {
                "thread_id": row["thread_id"],
                "nombre": row["nombre_cliente"],
                "whatsapp": row["whatsapp_id"],
                "metadata": row["metadata"]
            }
        return None
    except Exception as e:
        logger.error(f"Error al obtener thread: {e}")
        return None
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
    """
    Inserta un evento en la tabla audit_events.
    """
    conn = None
    try:
        conn = await get_db_connection()
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
        logger.info(f"Evento de auditoría registrado: {trace_id} - {event_type}")
        return True
    except Exception as e:
        logger.error(f"Error al registrar evento de auditoría: {e}")
        return False
    finally:
        if conn:
            await conn.close()
