"""
price_extractor.py - Extracción de precios desde URLs con caché y manejo de errores.
VERSIÓN 1.0 – Solo para URLs de AISA Solar 29JUL2026.
"""
import time
import logging
import requests
from bs4 import BeautifulSoup
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)
CACHE_TTL = 3600  # 1 hora
_cache = {}
_cache_time = {}

def extract_price_from_url(url: str) -> Optional[float]:
    """
    Extrae el precio (en GTQ) desde la URL del producto.
    Retorna None si no se puede extraer o si la URL no es accesible.
    """
    if not url:
        return None

    # Verificar caché
    now = time.time()
    if url in _cache and (now - _cache_time.get(url, 0)) < CACHE_TTL:
        return _cache[url]

    try:
        # Descargar la página
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()

        # Parsear HTML y buscar precio (esto debe adaptarse a la estructura real de AISA)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Ejemplo de selectores (debes ajustarlos)
        price_elem = soup.select_one('.price .amount, .product-price .amount, .woocommerce-Price-amount')
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            # Limpiar: eliminar 'Q', 'GTQ', comas, espacios
            price_clean = price_text.replace('Q', '').replace('GTQ', '').replace(',', '').strip()
            try:
                price = float(price_clean)
                _cache[url] = price
                _cache_time[url] = now
                logger.info(f"Precio extraído de {url}: {price} GTQ")
                return price
            except ValueError:
                logger.error(f"No se pudo convertir a número: {price_text}")

    except Exception as e:
        logger.error(f"Error al extraer precio de {url}: {e}")

    # Fallback: retornar None
    return None

def extract_prices_from_urls(urls: list) -> dict:
    """Extrae precios de múltiples URLs y retorna un diccionario {url: precio}."""
    result = {}
    for url in urls:
        if url:
            result[url] = extract_price_from_url(url)
    return result
