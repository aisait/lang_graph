"""
db_client.py - Cliente de base de datos con reintentos y manejo de errores.
"""
import os
import json
import asyncio
import asyncpg
import logging
from typing import Optional, List, Dict, Any
from agent_graph import normalizar_contacto

logger = logging.getLogger("jarvi.db")

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
    """
    Actualiza o inserta un thread en BI, acumulando costos de LLM.
    metadata_adicional se fusiona con la metadata existente.
    """
    conn = None
    try:
        _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
        db_url = get_bi_db_url()
        if not db_url:
            logger.error("BI_DATABASE_URL no configurada")
            return False
        conn = await get_db_connection(db_url)
        
        # Asegurar que metadata_adicional sea un diccionario
        if metadata_adicional is None:
            metadata_adicional = {}
        if not isinstance(metadata_adicional, dict):
            logger.error(f"metadata_adicional no es dict: {type(metadata_adicional)}")
            metadata_adicional = {}
            
        # Construir metadata base
        metadata = {
            "email": email,
            "productos": productos or [],
            "vendedor": vendedor,
            "trace_id": trace_id,
        }
        # Fusionar con metadata_adicional
        metadata.update(metadata_adicional)
        
        existing = await conn.fetchrow(
            "SELECT thread_id, metadata FROM threads WHERE whatsapp_id = $1",
            whatsapp_norm
        )
        if existing:
            old_meta = existing["metadata"] or {}
            # Asegurar que old_meta sea dict
            if isinstance(old_meta, str):
                try:
                    old_meta = json.loads(old_meta)
                except:
                    old_meta = {}
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

# ... (resto de funciones: registrar_evento_auditoria, acumular_costo_thread, obtener_costo_acumulado) sin cambios
