# db_migrate_unificado.py
"""
Migración unificada para JARVI 2.0 – Separa CTFOM y BI.
Ejecuta la migración en dos bases de datos distintas usando variables de entorno.
"""

import os
import sys
import asyncio
import asyncpg

# ---------------------------------------------------------------------
# DDL para CTFOM (telemetría, auditoría, checkpoints)
# ---------------------------------------------------------------------
DDL_CTFOM = """
-- Tablas de telemetría y auditoría (CTFOM)
CREATE TABLE IF NOT EXISTS telemetry_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id UUID NOT NULL,
    span_id UUID NOT NULL,
    parent_span_id UUID,
    thread_id VARCHAR(255),
    run_id VARCHAR(255),
    layer VARCHAR(50) NOT NULL,
    node_name VARCHAR(100),
    event_type VARCHAR(20) NOT NULL,
    latency_ms INTEGER,
    severity VARCHAR(20) DEFAULT 'INFO',
    error_code VARCHAR(50),
    cpu_percent FLOAT,
    memory_mb FLOAT,
    dispatch_success BOOLEAN,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_telemetry_trace_id ON telemetry_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_run_id ON telemetry_events (run_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry_events (created_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_error_code ON telemetry_events (error_code);

CREATE TABLE IF NOT EXISTS dispatch_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id UUID NOT NULL,
    channel VARCHAR(30) NOT NULL,
    payload_hash TEXT,
    dispatch_started TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatch_finished TIMESTAMPTZ,
    ack_received BOOLEAN DEFAULT FALSE,
    ack_latency_ms INTEGER,
    status VARCHAR(20) DEFAULT 'CREATED',
    error_code VARCHAR(50),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS system_health (
    service_name TEXT PRIMARY KEY,
    heartbeat_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    avg_latency_ms INTEGER,
    error_rate FLOAT,
    queue_depth INTEGER
);

INSERT INTO system_health (service_name, status)
VALUES ('api', 'UNKNOWN'), ('langgraph', 'UNKNOWN'), ('postgres', 'UNKNOWN'),
       ('odoo', 'UNKNOWN'), ('n8n', 'UNKNOWN'), ('langfuse', 'UNKNOWN')
ON CONFLICT (service_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS root_cause_analysis (
    incident_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    trace_id UUID,
    primary_failure TEXT,
    secondary_failure TEXT,
    tertiary_failure TEXT,
    confidence FLOAT,
    remediation TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Checkpoints de LangGraph (pueden estar en CTFOM o en su propia BD)
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

-- Tabla de auditoría de negocio (audit_events) – se mantiene en CTFOM
CREATE TABLE IF NOT EXISTS audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    event_type VARCHAR(50),
    source VARCHAR(50),
    system_snapshot JSONB,
    request_payload JSONB,
    langsmith_run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_thread_id ON audit_events(thread_id);
"""

# ---------------------------------------------------------------------
# DDL para BI (negocio: threads, resumenes, leads, etc.)
# ---------------------------------------------------------------------
DDL_BI = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id UUID PRIMARY KEY,
    nombre_cliente VARCHAR(255),
    whatsapp_id VARCHAR(50),
    chat_id TEXT,
    fingerprint TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_threads_chat_id ON threads (chat_id);
CREATE INDEX IF NOT EXISTS idx_threads_fingerprint ON threads (fingerprint);

CREATE TABLE IF NOT EXISTS resumenes (
    chat_id TEXT PRIMARY KEY,
    resumen TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_resumenes_created_at ON resumenes (created_at);
"""

async def run_migration(db_url: str, ddl: str, label: str):
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute(ddl)
        await conn.close()
        print(f"✅ Migración completada para {label}")
    except Exception as e:
        print(f"❌ Error en {label}: {e}")
        sys.exit(1)

async def main():
    ctfom_url = os.getenv("CTFOM_DATABASE_URL")
    bi_url = os.getenv("BI_DATABASE_URL")
    if not ctfom_url or not bi_url:
        raise RuntimeError("Faltan CTFOM_DATABASE_URL o BI_DATABASE_URL")
    await run_migration(ctfom_url, DDL_CTFOM, "CTFOM")
    await run_migration(bi_url, DDL_BI, "BI")

if __name__ == "__main__":
    asyncio.run(main())
