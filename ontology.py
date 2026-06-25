import os
import json
import logging
from typing import Optional, Dict, Any, List

# Configuración del Logger para observabilidad en Cloud Run
logger = logging.getLogger(__name__)

# Caché en memoria para evitar múltiples lecturas de disco
_ONTOLOGIA_CACHE: Optional[Dict[str, Any]] = None

# Fallback path configurable por variable de entorno
DEFAULT_JSON_PATH = os.getenv("ONTOLOGY_JSON_PATH", "catalog_ontology.json")


def cargar_ontologia(file_path: str = DEFAULT_JSON_PATH) -> Dict[str, Any]:
    """
    Carga de manera eficiente y centralizada la taxonomía desde el JSON externo.
    Aplica patrón Singleton en memoria sobre la ejecución del contenedor.
    """
    global _ONTOLOGIA_CACHE
    if _ONTOLOGIA_CACHE is not None:
        return _ONTOLOGIA_CACHE

    if not os.path.exists(file_path):
        logger.error(f"Falta el activo crítico de taxonomía en la ruta: {file_path}")
        raise FileNotFoundError(f"Archivo de ontología no encontrado en {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            _ONTOLOGIA_CACHE = json.load(f)
        logger.info(f"Ontología cargada exitosamente en memoria desde {file_path}. {len(_ONTOLOGIA_CACHE)} categorías indexadas.")
        return _ONTOLOGIA_CACHE
    except json.JSONDecodeError as je:
        logger.critical(f"Corrupción detectada en el esquema estructurado JSON: {str(je)}")
        raise
    except Exception as e:
        logger.critical(f"Fallo catastrófico en la lectura de ontología: {str(e)}")
        raise


def obtener_fragmento_ontologia(topologia: Optional[str]) -> str:
    """
    Ruteo epistemológico avanzado (Context Window Preservation / ISO 42001).
    Filtra los bloques requeridos basándose en la topología inyectada en el estado.
    """
    # Garantiza la resiliencia del mapeo ante fallas de carga de datos externos
    try:
        ontologia = cargar_ontologia()
    except Exception:
        # Mecanismo de degradación suave si el JSON falla en runtime
        return "Error interno de inicialización: Catálogo temporalmente indisponible."

    # Lógica determinista de ruteo semántico según topología técnica detectada
    if not topologia:
        bloques_requeridos = ["11", "12", "13", "14", "15", "18", "20", "26", "38", "46", "51"]
    elif "ON-GRID" in topologia.upper() or "ATADO" in topologia.upper():
        # Bloques de inyección On-Grid dedicados + infraestructura fotovoltaica base
        bloques_requeridos = [str(i) for i in range(1, 11)] + ["20", "35", "37", "38", "60", "61", "64", "79", "80", "81", "85"]
    elif "OFF-GRID" in topologia.upper() or "AISLADO" in topologia.upper():
        # Bloques Off-grid, kits autónomos, almacenamiento estacionario y refrigeración DC
        bloques_requeridos = ["14", "16", "18", "19", "20", "22", "23", "24", "26", "27", "28", "32", "34", "35", "45", "46", "50", "51", "52", "53", "62", "64", "81", "82", "86"]
    elif "BOMBA" in topologia.upper() or "HIDRO" in topologia.upper() or "BOMBEO" in topologia.upper():
        # Bloques hidrosanitarios, bombas sumergibles, presurizadores y controladores térmicos
        bloques_requeridos = ["12", "13", "15", "16", "39", "40", "41", "42", "55", "56", "57", "58", "59", "66", "73", "74", "77", "78", "83"]
    else:
        # Fallback por defecto (Categorías transversales de alta conversión: Calentadores, Paneles, Kits básicos)
        bloques_requeridos = ["11", "12", "13", "14", "15", "18", "20", "26", "38", "46", "51"]

    resultado: List[str] = []
    
    # Construcción limpia y estructurada del payload semántico para el contexto del LLM
    for bloque_id in bloques_requeridos:
        if bloque_id in ontologia:
            item = ontologia[bloque_id]
            resultado.append(
                f"Categoría [{bloque_id}]: {item['nombre']}\n"
                f"Enlace Directo: {item['url']}\n"
                f"Keywords de Validación: {', '.join(item['keywords'])}"
            )
        else:
            logger.warning(f"Se solicitó el bloque id '{bloque_id}', pero no está definido en el catálogo JSON.")

    return "\n\n".join(resultado)
