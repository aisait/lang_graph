"""
odoo_db_client.py - Cliente asíncrono para consultar la base de datos PostgreSQL de Odoo.
VERSIÓN 1.3 – Lectura directa de variables de entorno con logs de depuración.
17AGO2026.
"""
import os
import logging
import asyncio
from typing import List, Dict, Optional, Any
import asyncpg
from config import settings

logger = logging.getLogger(__name__)

class OdooDBClient:
    """Cliente para consultar product_template y mrp_bom directamente desde PostgreSQL."""

    def __init__(self):
        # Lectura directa de variables de entorno (con fallback a settings)
        self.host = os.getenv("DATABASE_HOST") or settings.odoo_db_host
        self.port = int(os.getenv("DATABASE_PORT") or settings.odoo_db_port or 5432)
        self.database = os.getenv("DATABASE_PROD") or settings.odoo_db_name
        self.user = os.getenv("DATABASE_USER") or settings.odoo_db_user
        self.password = os.getenv("DATABASE_PASSWORD") or settings.odoo_db_password
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False
        self._connection_attempts = 0
        self._max_retries = 3
        self._last_error: Optional[str] = None
        self._connection_history: List[Dict] = []

        # Log de depuración para verificar valores
        logger.info(f"[ODOO-DB] Configuración: host={self.host}, port={self.port}, database={self.database}, user={self.user}")

    async def connect(self) -> bool:
        """Inicializa el pool de conexiones a la BD de Odoo con 3 reintentos."""
        if self._initialized:
            return True

        self._connection_attempts = 0
        self._connection_history = []

        while self._connection_attempts < self._max_retries:
            self._connection_attempts += 1
            attempt_info = {
                "attempt": self._connection_attempts,
                "timestamp": str(asyncio.get_event_loop().time()),
                "host": self.host,
                "port": self.port,
                "database": self.database
            }

            logger.info(f"[ODOO-DB] 🔄 Intento de conexión #{self._connection_attempts} a {self.host}:{self.port}/{self.database}")

            try:
                self.pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    min_size=1,
                    max_size=5,
                    timeout=10.0
                )

                # Verificar conexión con una consulta simple
                async with self.pool.acquire() as conn:
                    result = await conn.fetchval("SELECT 1")
                    if result == 1:
                        self._initialized = True
                        self._last_error = None
                        attempt_info["status"] = "success"
                        self._connection_history.append(attempt_info)
                        logger.info(f"[ODOO-DB] ✅ Conexión establecida correctamente (intento #{self._connection_attempts})")
                        return True
                    else:
                        raise Exception("Falló la consulta de verificación")

            except Exception as e:
                self._initialized = False
                self._last_error = str(e)
                attempt_info["status"] = "failed"
                attempt_info["error"] = str(e)
                self._connection_history.append(attempt_info)
                logger.error(f"[ODOO-DB] ❌ Error en conexión #{self._connection_attempts}: {self._last_error}")

                if self._connection_attempts < self._max_retries:
                    wait_time = 3 * self._connection_attempts
                    logger.info(f"[ODOO-DB] ⏳ Reintentando en {wait_time} segundos...")
                    await asyncio.sleep(wait_time)

        logger.error(f"[ODOO-DB] ❌ Máximo de reintentos alcanzado ({self._max_retries}). Todas las conexiones fallaron.")
        return False

    async def close(self):
        if self.pool:
            await self.pool.close()
            self._initialized = False
            logger.info("[ODOO-DB] Conexión cerrada.")

    async def ensure_connected(self) -> bool:
        """Asegura que la conexión esté activa, reconecta si es necesario."""
        if self._initialized:
            try:
                async with self.pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                    return True
            except Exception as e:
                logger.warning(f"[ODOO-DB] Conexión perdida: {e}. Reconectando...")
                self._initialized = False
                return await self.connect()
        return await self.connect()

    async def search_products_by_keyword(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Busca productos cuyo nombre o website_meta_keyword contengan la keyword.
        Retorna lista de diccionarios con los campos principales.
        """
        if not await self.ensure_connected():
            logger.warning("[ODOO-DB] ⚠️ No se pudo establecer conexión, retornando lista vacía")
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, name, list_price,
                           website_meta_keyword, description_website,
                           data_sheet_auto, type, categ_id
                    FROM product_template
                    WHERE website_meta_keyword ILIKE '%' || $1 || '%'
                       OR name ILIKE '%' || $1 || '%'
                    LIMIT $2
                """, keyword, limit)
                results = [dict(r) for r in rows]
                if results:
                    logger.info(f"[ODOO-DB] ✅ Búsqueda por '{keyword}': {len(results)} resultados")
                    for r in results:
                        logger.info(f"[ODOO-DB]    - {r.get('name')} (Q {r.get('list_price')})")
                else:
                    logger.info(f"[ODOO-DB] ℹ️ Búsqueda por '{keyword}': 0 resultados")
                return results
        except Exception as e:
            logger.error(f"[ODOO-DB] ❌ Error en búsqueda: {e}")
            self._initialized = False
            return []

    def format_price(self, price: Optional[float]) -> str:
        """Formatea el precio en Quetzales (Q) con dos decimales."""
        if price is None:
            return "Precio bajo consulta"
        try:
            return f"Q {price:,.2f}".replace(",", ".")
        except:
            return "Precio bajo consulta"

    def get_connection_status(self) -> dict:
        """Retorna el estado completo de la conexión para diagnóstico."""
        return {
            "connected": self._initialized,
            "attempts": self._connection_attempts,
            "max_retries": self._max_retries,
            "last_error": self._last_error,
            "history": self._connection_history,
            "host": self.host,
            "port": self.port,
            "database": self.database
        }


# Instancia global
odoo_db_client = OdooDBClient()
