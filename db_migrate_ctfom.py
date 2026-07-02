"""
db_migrate_ctfom.py
Migración del esquema de telemetría cognitiva (CTFOM) para JARVI 2.0.03.
Crea las tablas de observabilidad, trazabilidad, despacho, salud del sistema
y análisis de causa raíz, con particionamiento temporal en telemetry_events.

Ejecución:
    python db_migrate_ctfom.py

Dependencias: psycopg (v3), variable de entorno DATABASE_URL.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
import psycopg
from psycopg import AsyncConnection

# ---------------------------------------------------------------------------
# DDL del módulo CTFOM (idempotente)
# ---------------------------------------------------------------------------
CTFOM_DDL = """
-- =========================================================================
-- 1. Tabla principal de telemetría (particionada por mes)
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

-- =========================================================================
-- 2. Índices sobre la tabla particionada (se heredan en cada partición)
-- =========================================================================
CREATE INDEX IF NOT EXISTS idx_telemetry_trace_id ON telemetry_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_run_id ON telemetry_events (run_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry_events (created_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_error_code ON telemetry_events (error_code);
CREATE INDEX IF NOT EXISTS idx_telemetry_gin_metadata ON telemetry_events USING GIN (metadata);

-- =========================================================================
-- 3. Función para crear particiones mensuales dinámicamente
--    (se llama una vez y luego puede programarse con pg_cron o similar)
-- =========================================================================
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

-- =========================================================================
-- 4. Tabla de eventos de despacho (entrega a canales)
-- =========================================================================
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

-- =========================================================================
-- 5. Tabla de salud del sistema (heartbeat de servicios)
-- =========================================================================
CREATE TABLE IF NOT EXISTS system_health (
    service_name TEXT PRIMARY KEY,
    heartbeat_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    avg_latency_ms INTEGER,
    error_rate FLOAT,
    queue_depth INTEGER
);

-- =========================================================================
-- 6. Tabla de análisis de causa raíz
-- =========================================================================
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

-- =========================================================================
-- 7. Insertar servicios iniciales en system_health
-- =========================================================================
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
    Ejecuta la migración CTFOM de manera atómica.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ Error: DATABASE_URL no encontrada en el entorno.")
        sys.exit(1)

    # Eliminar parámetros no soportados (ej. pool_size)
    if "pool_size" in db_url:
        from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
        parsed = urlparse(db_url)
        query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "pool_size"]
        db_url = urlunparse(parsed._replace(query=urlencode(query)))

    print("🚀 Iniciando migración del módulo CTFOM...")
    try:
        async with await AsyncConnection.connect(db_url) as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    # Ejecutar DDL de tablas e índices
                    await cur.execute(CTFOM_DDL)
                    # Crear particiones para los próximos 12 meses
                    await cur.execute("SELECT create_monthly_partitions();")
        print("✅ Migración CTFOM completada exitosamente.")
    except Exception as e:
        print(f"❌ Error crítico durante la migración CTFOM: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_migration())
