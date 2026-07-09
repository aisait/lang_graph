import json, os, unicodedata, difflib, logging
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
        return _UBICACION_CACHE
    except Exception as e:
        logger.error(f"Error al cargar ubicaciones: {e}")
        return []

def normalizar_texto(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def buscar_ubicacion(texto: str) -> Optional[Dict[str, str]]:
    if not texto:
        return None
    ubicaciones = cargar_ubicacion()
    texto_norm = normalizar_texto(texto)
    mejor = None
    mejor_ratio = 0.0
    for entry in ubicaciones:
        for alias in [normalizar_texto(a) for a in entry.get("aliases", [])]:
            ratio = difflib.SequenceMatcher(None, texto_norm, alias).ratio()
            # Umbral adaptativo: si la longitud del texto es corta (<5), exigimos mayor ratio (0.85)
            umbral = 0.85 if len(texto_norm) < 5 else 0.75
            if ratio > mejor_ratio and ratio >= umbral:
                mejor_ratio = ratio
                mejor = entry
    if mejor:
        return {"municipio": mejor["municipio"], "departamento": mejor["departamento"], "label": mejor["label"]}
    return None
