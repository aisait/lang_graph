"""
db_migrate_unificado.py
Migración unificada del esquema de base de datos para JARVI 2.0.03 (Core + CTFOM).
Crea todas las tablas necesarias en una única transacción atómica e idempotente.

Ejecución:
    python db_migrate_unificado.py

Estándares aplicados:
- ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
"""

import asyncio
import os
import sys
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import psycopg
from psycopg import AsyncConnection

# ---------------------------------------------------------------------------
# Esquema DDL completo (Core + CTFOM)
# ---------------------------------------------------------------------------
DDL_UNIFICADO = """
-- =========================================================================
-- 1. Sistema de checkpoints de LangGraph
-- =========================================================================
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

-- =========================================================================
-- 2. Trazabilidad 360° Personalizada
-- =========================================================================
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

CREATE INDEX IF NOT EXISTS idx_audit_thread_id ON audit_events(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_events(langsmith_run_id);

-- =========================================================================
-- 3. Módulo CTFOM: Telemetría cognitiva
-- =========================================================================
CREATE TABLE IF NOT EXISTS telemetry_events (
    id BIGSERIAL,
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
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS idx_telemetry_trace_id ON telemetry_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_run_id ON telemetry_events (run_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry_events (created_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_error_code ON telemetry_events (error_code);
CREATE INDEX IF NOT EXISTS idx_telemetry_gin_metadata ON telemetry_events USING GIN (metadata);

CREATE OR REPLACE FUNCTION create_monthly_partitions(
    start_date DATE DEFAULT date_trunc('month', now())::DATE,
    months_ahead INTEGER DEFAULT 12
) RETURNS void AS $$
DECLARE
    partition_date DATE;
    partition_name TEXT;
    start_of_month TEXT;
    end_of_month TEXT;
BEGIN
    FOR i IN 0..months_ahead LOOP
        partition_date := start_date + (i || ' months')::INTERVAL;
        partition_name := 'telemetry_events_' || to_char(partition_date, 'YYYY_MM');
        start_of_month := to_char(partition_date, 'YYYY-MM-01');
        end_of_month := to_char((partition_date + INTERVAL '1 month')::DATE, 'YYYY-MM-01');
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry_events FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_of_month, end_of_month
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;

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

INSERT INTO system_health (service_name, status)
VALUES
    ('api', 'UNKNOWN'),
    ('langgraph', 'UNKNOWN'),
    ('postgres', 'UNKNOWN'),
    ('odoo', 'UNKNOWN'),
    ('streamlit', 'UNKNOWN'),
    ('n8n', 'UNKNOWN'),
    ('langsmith', 'UNKNOWN')
ON CONFLICT (service_name) DO NOTHING;
"""


async def run_migration():
    """
    Ejecuta la migración completa (Core + CTFOM) en una única transacción atómica.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL no encontrada en el entorno.")
        sys.exit(1)

    # Filtro de inmunidad sintáctica para parámetros no nativos de psycopg v3
    if "pool_size" in db_url:
        parsed_url = urlparse(db_url)
        query_params = parse_qsl(parsed_url.query)
        filtered_params = [(k, v) for k, v in query_params if k != "pool_size"]
        db_url = urlunparse(parsed_url._replace(query=urlencode(filtered_params)))

    print("🚀 Iniciando migración unificada de base de datos...")
    try:
        async with await AsyncConnection.connect(db_url) as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(DDL_UNIFICADO)
                    # Generar particiones de telemetría para los próximos 12 meses
                    await cur.execute("SELECT create_monthly_partitions();")
        print("✅ Migración unificada completada exitosamente (Core + CTFOM).")
    except Exception as e:
        print(f"❌ Error crítico en migración unificada: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_migration())
