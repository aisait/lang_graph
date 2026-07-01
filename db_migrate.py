"""
db_migrate.py
Script de migración de esquema de base de datos para JARVI 2.0.
Crea las tablas necesarias para la persistencia del grafo (LangGraph)
y la trazabilidad 360° de auditoría (threads, audit_events).

Estándares aplicados:
- ISO/IEC/IEEE 12207:2008 (Ciclo de vida del software): este script es un
  "procedimiento de instalación" que garantiza la correcta configuración
  del entorno de producción.
- ISO/IEC 26514:2021 (Documentación de software): cada sentencia DDL está
  comentada y se documenta su propósito.
- ISO/IEC 25010:2011 (Calidad del producto): el DDL es idempotente (IF NOT EXISTS)
  y atómico (transacción), cumpliendo con la característica de "fiabilidad".
- ISO/IEC 29119:2022 (Pruebas de software - caja negra):
  Pruebas sugeridas:
  1. Ejecutar el script con DATABASE_URL válida: debe mostrar "Migración completada exitosamente".
  2. Ejecutar el script sin DATABASE_URL: debe mostrar "DATABASE_URL no encontrada en el entorno" y terminar con código 1.
  3. Ejecutar dos veces seguidas: no debe producir errores (idempotencia).
  4. Verificar en PostgreSQL la existencia de las tablas: checkpoints, checkpoint_blobs,
     threads, audit_events y los índices idx_audit_thread_id, idx_audit_run_id.
"""

import asyncio
import os
import sys
import psycopg
from psycopg import AsyncConnection
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ---------------------------------------------------------------------------
# Esquema DDL atómico e idempotente (propiedad intelectual de AISA Solar)
# ---------------------------------------------------------------------------
DDL_SCHEMA = """
-- 1. LangGraph Native Checkpoint System
-- Tabla principal de checkpoints del grafo. Almacena el estado serializado
-- de cada thread y checkpoint_id.
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- Blobs binarios asociados a los checkpoints (canales del grafo)
CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

-- 2. Trazabilidad 360° Personalizada
-- Tabla de sesiones (threads) para almacenar metadatos del cliente
CREATE TABLE IF NOT EXISTS threads (
    thread_id UUID PRIMARY KEY,
    nombre_cliente VARCHAR(255),
    whatsapp_id VARCHAR(50),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de eventos de auditoría (cada ejecución del grafo o llamada a la API)
CREATE TABLE IF NOT EXISTS audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID REFERENCES threads(thread_id),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    event_type VARCHAR(50),
    source VARCHAR(50),
    system_snapshot JSONB,
    request_payload JSONB,
    langsmith_run_id TEXT
);

-- 3. Índices de Rendimiento
-- Aceleran las consultas de auditoría por thread y por run_id
CREATE INDEX IF NOT EXISTS idx_audit_thread_id ON audit_events(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_events(langsmith_run_id);
"""


async def run_migration():
    """
    Punto de entrada asíncrono para ejecutar la migración del esquema.

    Prueba de caja negra:
        - Sin DATABASE_URL: termina con sys.exit(1) y mensaje de error.
        - Con DATABASE_URL correcta: ejecuta DDL_SCHEMA en una transacción atómica.
        - Si ocurre un error de conexión: captura la excepción y termina con sys.exit(1).
    """
    # -----------------------------------------------------------------------
    # Obtener la URL de conexión desde la variable de entorno DATABASE_URL
    # -----------------------------------------------------------------------
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL no encontrada en el entorno.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Filtro de inmunidad sintáctica: elimina parámetros no soportados por
    # psycopg v3 (como pool_size) que algunas plataformas añaden automáticamente.
    # -----------------------------------------------------------------------
    if "pool_size" in db_url:
        parsed_url = urlparse(db_url)
        query_params = parse_qsl(parsed_url.query)
        # Filtrar solo 'pool_size'; se pueden añadir otros parámetros problemáticos
        filtered_params = [(k, v) for k, v in query_params if k != "pool_size"]
        db_url = urlunparse(parsed_url._replace(query=urlencode(filtered_params)))

    print("🚀 Iniciando migración de esquema...")
    try:
        # -------------------------------------------------------------------
        # Conexión asíncrona dedicada y aislada (no usa el pool)
        # -------------------------------------------------------------------
        async with await AsyncConnection.connect(db_url) as conn:
            # -------------------------------------------------------------------
            # Transacción explícita para garantizar atomicidad del DDL
            # -------------------------------------------------------------------
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(DDL_SCHEMA)
        print("✅ Migración completada exitosamente.")
    except Exception as e:
        print(f"❌ Error crítico en migración: {e}")
        sys.exit(1)


if __name__ == "__main__":
    """
    Ejecución directa del script. En producción, se llama desde la línea
    de comandos: python db_migrate.py
    """
    asyncio.run(run_migration())
