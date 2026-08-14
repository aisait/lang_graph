"""
odoo_db_client.py - Cliente asíncrono para consultar la base de datos PostgreSQL de Odoo.
VERSIÓN 1.0 – 14AGO2026.
"""
import os
import logging
from typing import List, Dict, Optional, Any
import asyncpg
from config import settings

logger = logging.getLogger(__name__)

class OdooDBClient:
    """Cliente para consultar product_template y mrp_bom directamente desde PostgreSQL."""

    def __init__(self):
        self.host = settings.odoo_db_host
        self.port = settings.odoo_db_port
        self.database = settings.odoo_db_name
        self.user = settings.odoo_db_user
        self.password = settings.odoo_db_password
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    async def connect(self) -> bool:
        """Inicializa el pool de conexiones a la BD de Odoo."""
        if self._initialized:
            return True
        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=1,
                max_size=5
            )
            self._initialized = True
            logger.info("✅ Conexión a BD de Odoo establecida correctamente.")
            return True
        except Exception as e:
            logger.error(f"❌ Error al conectar a BD de Odoo: {e}")
            self._initialized = False
            return False

    async def close(self):
        if self.pool:
            await self.pool.close()
            self._initialized = False
            logger.info("Conexión a BD de Odoo cerrada.")

    async def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene un producto por su ID (product_template)."""
        if not self._initialized:
            await self.connect()
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, name, list_price,
                       website_meta_keyword, description_website,
                       data_sheet_auto, type, categ_id
                FROM product_template
                WHERE id = $1
            """, product_id)
            return dict(row) if row else None

    async def search_products_by_keyword(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Busca productos cuyo nombre o website_meta_keyword contengan la keyword.
        Retorna lista de diccionarios con los campos principales.
        """
        if not self._initialized:
            await self.connect()
        if not self.pool:
            return []
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
            return [dict(r) for r in rows]

    async def get_products_by_category(self, categ_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Obtiene productos de una categoría específica."""
        if not self._initialized:
            await self.connect()
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, list_price,
                       website_meta_keyword, description_website,
                       data_sheet_auto
                FROM product_template
                WHERE categ_id = $1
                LIMIT $2
            """, categ_id, limit)
            return [dict(r) for r in rows]

    async def get_bom_components(self, product_tmpl_id: int) -> List[Dict[str, Any]]:
        """
        Retorna los componentes de la lista de materiales (mrp_bom)
        para un product_tmpl_id dado.
        """
        if not self._initialized:
            await self.connect()
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT bom.product_id, bom.product_qty, pt.name, pt.list_price
                FROM mrp_bom bom
                JOIN product_template pt ON bom.product_id = pt.id
                WHERE bom.product_tmpl_id = $1
            """, product_tmpl_id)
            return [dict(r) for r in rows]

    def format_price(self, price: Optional[float]) -> str:
        """Formatea el precio en Quetzales (Q) con dos decimales."""
        if price is None:
            return "Precio bajo consulta"
        try:
            return f"Q {price:,.2f}".replace(",", ".")
        except:
            return "Precio bajo consulta"


# Instancia global (se inicializará en el lifespan de la API)
odoo_db_client = OdooDBClient()
