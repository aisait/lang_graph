"""
ubicacion.py - Validación de municipios y departamentos con fuzzy matching.
"""
import json
import os
import unicodedata
import difflib
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

_UBICACION_CACHE = None
UBICACION_PATH = os.getenv("UBICACION_JSON_PATH", os.path.join(os.path.dirname(__file__), "departamento_municipio.json"))

def cargar_ubicacion() -> list:
    global _UBICACION_CACHE
    if _UBICACION_CACHE is not None:
        return _UBICACION_CACHE
    try:
        with open(UBICACION_PATH, "r", encoding="utf-8") as f:
            _UBICACION_CACHE = json.load(f)
        logger.info(f"Ubicaciones cargadas: {len(_UBICACION_CACHE)} municipios.")
        return _UBICACION_CACHE
    except Exception as e:
        logger.error(f"Error al cargar ubicaciones: {e}")
        return []

def normalizar_texto(texto: str) -> str:
    """Elimina tildes y convierte a minúsculas."""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def buscar_ubicacion(texto: str) -> Optional[Dict[str, str]]:
    """
    Busca un municipio por su nombre o alias, con fuzzy matching.
    Retorna {'municipio': ..., 'departamento': ..., 'label': ...} o None.
    """
    if not texto:
        return None
    ubicaciones = cargar_ubicacion()
    texto_norm = normalizar_texto(texto)
    mejor_coincidencia = None
    mejor_ratio = 0.0
    for entry in ubicaciones:
        aliases = [normalizar_texto(a) for a in entry.get("aliases", [])]
        for alias in aliases:
            ratio = difflib.SequenceMatcher(None, texto_norm, alias).ratio()
            if ratio > mejor_ratio:
                mejor_ratio = ratio
                mejor_coincidencia = entry
    if mejor_coincidencia and mejor_ratio > 0.75:  # Umbral de confianza
        logger.info(f"Ubicación encontrada: {mejor_coincidencia['label']} (ratio: {mejor_ratio:.2f})")
        return {
            "municipio": mejor_coincidencia["municipio"],
            "departamento": mejor_coincidencia["departamento"],
            "label": mejor_coincidencia["label"]
        }
    logger.warning(f"No se encontró ubicación para: {texto}")
    return None
