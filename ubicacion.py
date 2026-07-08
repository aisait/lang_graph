# ubicacion.py
import json
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_UBICACION_CACHE = None
UBICACION_PATH = os.getenv("UBICACION_JSON_PATH", os.path.join(os.path.dirname(__file__), "departamento_municipio.json"))

def cargar_ubicacion() -> list:
    """Carga y cachea el JSON de municipios."""
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

def buscar_ubicacion(texto: str) -> Optional[Dict[str, str]]:
    """
    Busca un municipio por su nombre o alias en el JSON.
    Retorna {'municipio': ..., 'departamento': ..., 'label': ...} o None.
    """
    if not texto:
        return None
    ubicaciones = cargar_ubicacion()
    texto = texto.lower().strip()
    for entry in ubicaciones:
        municipio = entry.get("municipio", "").lower()
        departamento = entry.get("departamento", "").lower()
        label = entry.get("label", "").lower()
        aliases = [alias.lower() for alias in entry.get("aliases", [])]
        if (municipio == texto or
            departamento == texto or
            label == texto or
            texto in aliases or
            any(alias in texto or texto in alias for alias in aliases)):
            logger.info(f"Ubicación encontrada: {entry['label']}")
            return {
                "municipio": entry["municipio"],
                "departamento": entry["departamento"],
                "label": entry["label"]
            }
    logger.warning(f"No se encontró ubicación para: {texto}")
    return None
