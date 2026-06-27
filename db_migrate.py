import asyncio
import os
import sys
import psycopg
from psycopg import AsyncConnection

# DDL Atómico e Idempotente - PROPIEDAD INTELECTUAL DE AISA SOLAR
DDL_SCHEMA = """
-- 1. LangGraph Native Checkpoint System
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
CREATE TABLE IF NOT EXISTS threads (
    thread_id UUID PRIMARY KEY,
    nombre_cliente VARCHAR(255),
    whatsapp_id VARCHAR(50),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

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
CREATE INDEX IF NOT EXISTS idx_audit_thread_id ON audit_events(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_events(langsmith_run_id);
"""

async def run_migration():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL no encontrada en el entorno.")
        sys.exit(1)

    print("🚀 Iniciando migración de esquema...")
    try:
        # Configurar conexión asíncrona dedicada y aislada
        async with await AsyncConnection.connect(db_url) as conn:
            # Forzar manejo de transacción explícita y atómica
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(DDL_SCHEMA)
        print("✅ Migración completada exitosamente.")
    except Exception as e:
        print(f"❌ Error crítico en migración: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_migration())
