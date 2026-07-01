"""
odoo_client.py
Cliente de conexión a Odoo ERP para JARVI 2.0.
Proporciona funciones asíncronas para autenticar y consultar el modelo
de productos, sin dependencia de Streamlit. Utiliza caché con TTL para
optimizar las consultas y logging para trazabilidad.

Estándares aplicados:
- ISO/IEC/IEEE 12207:2008 (Ciclo de vida): este módulo es un componente
  reutilizable del sistema.
- ISO/IEC 26514:2021 (Documentación): se documentan todas las funciones
  con sus parámetros, retornos y pruebas de caja negra.
- ISO/IEC 25010:2011 (Calidad): las funciones son asíncronas para no
  bloquear el event loop (eficiencia de desempeño) y usan caché para
  reducir la latencia (utilización de recursos).
- ISO/IEC 29119:2022 (Pruebas de software - caja negra):
  Pruebas sugeridas:
  1. Sin conexión al ERP: las funciones deben devolver None sin lanzar excepciones.
  2. Con conexión correcta: obtener_uid_odoo() debe devolver un entero (uid).
  3. ejecutar_odoo con modelo/producto válido debe devolver una lista de diccionarios.
  4. obtener_productos_on_grid_odoo() debe devolver una lista de productos cuyos
     campos incluyan 'name', 'list_price', etc.
  5. El caché de productos debe expirar tras 600 segundos (TTL) y renovarse en
     la siguiente llamada.
"""

import asyncio
import json
import logging
from functools import lru_cache
from typing import Optional, Any, List, Dict
from xmlrpc import client as xmlrpc_client
import time

import config
from audit import auditar_fase

# ---------------------------------------------------------------------------
# Logger para observabilidad en el backend (sin Streamlit)
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caché de autenticación de Odoo
# ---------------------------------------------------------------------------
_odoo_uid: Optional[int] = None
"""UID del usuario autenticado en Odoo, compartido entre todas las sesiones."""
_odoo_uid_lock = asyncio.Lock()
"""Lock asíncrono para evitar condiciones de carrera al refrescar el UID."""


async def obtener_uid_odoo() -> Optional[int]:
    """
    Establece y cachea la sesión de autenticación con el ERP Odoo.
    La autenticación se realiza mediante XML-RPC y el UID se almacena en memoria
    para reutilizarlo en todas las consultas posteriores.

    Retorna:
        int | None: UID del usuario si la autenticación es exitosa, None en caso de error.

    Prueba de caja negra (ISO/IEC 29119):
        - Primera llamada: debe realizar la autenticación y devolver un entero.
        - Llamadas subsecuentes: debe devolver el mismo UID sin reautenticar.
        - Si las credenciales son incorrectas, debe devolver None y registrar un error.
    """
    global _odoo_uid
    async with _odoo_uid_lock:
        if _odoo_uid is not None:
            return _odoo_uid
        try:
            # Nota: xmlrpc.client.ServerProxy no es asíncrono; se ejecuta en un hilo
            # mediante asyncio.to_thread para no bloquear el event loop.
            common = await asyncio.to_thread(
                xmlrpc_client.ServerProxy,
                f"http://{config.ODOO_HOST}:8069/xmlrpc/2/common"
            )
            _odoo_uid = await asyncio.to_thread(
                common.authenticate,
                config.ODOO_DB,
                config.ODOO_USER,
                config.ODOO_PASSWORD,
                {}
            )
            if _odoo_uid:
                logger.info("Autenticación exitosa en Odoo. UID: %s", _odoo_uid)
            else:
                logger.error("Fallo de autenticación en Odoo: credenciales inválidas")
            return _odoo_uid
        except Exception as e:
            logger.error("No se pudo autenticar en Odoo: %s", e)
            return None


async def ejecutar_odoo(modelo: str, metodo: str, *args, **kwargs) -> Optional[Any]:
    """
    Ejecuta un método XML-RPC genérico contra el ERP Odoo.
    Utiliza el UID cacheado para evitar reautenticar en cada llamada.

    Parámetros:
        modelo (str): nombre técnico del modelo Odoo (ej. 'product.template').
        metodo (str): método a invocar (ej. 'search_read').
        *args: argumentos posicionales para el método.
        **kwargs: argumentos nominales para el método.

    Retorna:
        Resultado del método Odoo, o None si ocurre un error.

    Prueba de caja negra:
        - Con modelo y método válidos: debe retornar una lista/valor según la operación.
        - Con modelo inexistente: debe loguear error y devolver None.
        - Con Odoo inaccesible: debe loguear error y devolver None.
    """
    uid = await obtener_uid_odoo()
    if uid is None:
        return None
    try:
        models = await asyncio.to_thread(
            xmlrpc_client.ServerProxy,
            f"http://{config.ODOO_HOST}:8069/xmlrpc/2/object"
        )
        resultado = await asyncio.to_thread(
            models.execute_kw,
            config.ODOO_DB,
            uid,
            config.ODOO_PASSWORD,
            modelo,
            metodo,
            args,
            kwargs
        )
        return resultado
    except Exception as e:
        logger.error("Error de ejecución en modelo ERP %s: %s", modelo, e)
        return None


# ---------------------------------------------------------------------------
# Caché de productos On‑Grid con TTL (600 segundos)
# ---------------------------------------------------------------------------
_cached_productos: Optional[List[Dict]] = None
_timestamp_productos: float = 0.0
_productos_lock = asyncio.Lock()


async def obtener_productos_on_grid_odoo() -> Optional[List[Dict]]:
    """
    Consulta y cachea la ficha técnica de productos On‑Grid desde Odoo.
    Los resultados se almacenan en memoria durante 10 minutos (TTL).

    Retorna:
        list[dict] | None: Lista de diccionarios con los campos 'name',
        'description_sale', 'list_price', 'website_url', 'default_code',
        o None si la consulta falla.

    Prueba de caja negra:
        - Primera llamada: debe consultar Odoo y devolver la lista de productos.
        - Segunda llamada antes del TTL: debe devolver la misma lista sin consultar Odoo.
        - Después del TTL: la siguiente llamada debe volver a consultar Odoo.
        - Si Odoo devuelve una lista vacía, debe devolver [].
        - Si Odoo no está disponible, debe devolver None.
    """
    global _cached_productos, _timestamp_productos

    async with _productos_lock:
        ahora = time.time()
        if _cached_productos is not None and (ahora - _timestamp_productos) < 600:
            return _cached_productos

        # Preparar dominio
        try:
            domain = json.loads(config.ODOO_ONGRID_DOMAIN)
        except Exception:
            domain = [("sale_ok", "=", True), ("type", "=", "product")]

        fields = ["name", "description_sale", "list_price", "website_url", "default_code"]
        productos = await ejecutar_odoo(
            config.ODOO_PRODUCT_MODEL,
            "search_read",
            [domain],
            {"fields": fields, "limit": 50}
        )
        if productos is not None:
            _cached_productos = productos
            _timestamp_productos = ahora
        return productos
