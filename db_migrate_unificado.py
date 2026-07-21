#!/usr/bin/env python3
# db_migrate_unificado.py - CORREGIDO (elimina TODOS los parámetros de pool)
import os
import sys
import asyncio
import asyncpg
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def sanear_db_url(db_url: str) -> str:
    """Elimina cualquier parámetro de la URL que contenga 'pool' o 'max_overflow'."""
    if not db_url:
        return db_url
    parsed = urlparse(db_url)
    query = parse_qs(parsed.query)
    # Eliminar TODAS las claves que contengan "pool" o "max_overflow" (insensible a mayúsculas)
    for key in list(query.keys()):
        if 'pool' in key.lower() or 'max_overflow' in key.lower():
            del query[key]
    clean_query = urlencode(query, doseq=True)
    # Reconstruir la URL
    cleaned = urlunparse(parsed._replace(query=clean_query))
    print(f"[DEBUG] URL original: {db_url}")
    print(f"[DEBUG] URL saneada:  {cleaned}")
    return cleaned

# =============================================================================
# DDL (el mismo que ya tiene, sin cambios)
# =============================================================================
DDL_CTFOM = """
-- (tu DDL de CTFOM aquí, igual que antes)
"""
DDL_BI = """
-- (tu DDL de BI aquí, igual que antes)
"""

async def run_migration(db_url: str, ddl: str, label: str):
    try:
        clean = sanear_db_url(db_url)
        print(f"Conectando a {label} con URL saneada...")
        conn = await asyncpg.connect(clean)
        print(f"Ejecutando DDL en {label}...")
        await conn.execute(ddl)
        await conn.close()
        print(f"✅ Migración completada para {label}")
    except Exception as e:
        print(f"❌ Error en {label}: {e}")
        sys.exit(1)

async def main():
    ctfom = os.getenv("CTFOM_DATABASE_URL")
    bi = os.getenv("BI_DATABASE_URL")
    if not ctfom or not bi:
        raise RuntimeError("Faltan CTFOM_DATABASE_URL o BI_DATABASE_URL")
    print("=== Migración JARVI 2.0 (versión mejorada) ===")
    await run_migration(ctfom, DDL_CTFOM, "CTFOM")
    await run_migration(bi, DDL_BI, "BI")
    print("✅ Todo listo")

if __name__ == "__main__":
    asyncio.run(main())
