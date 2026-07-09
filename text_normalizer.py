"""
text_normalizer.py
Módulo para normalización de texto, corrección ortográfica y fuzzy matching.
Usa symspellpy para corrección rápida, rapidfuzz para coincidencia difusa.
Cumple con ISO/IEC 25010 (Fiabilidad, Eficiencia) e ISO/IEC 29119 (Pruebas).
"""

import os
import re
import unicodedata
import logging
from typing import List, Optional, Tuple, Dict, Any

# Librerías externas
from symspellpy import SymSpell, Verbosity
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# =============================================================================
# Carga del diccionario de corrección ortográfica (descargar previamente)
# =============================================================================
SYMSPELL_PATH = os.getenv("SYMSPELL_DICT_PATH", "spanish_dictionary.txt")
# Nota: Descargar de https://github.com/wolfgarbe/SymSpell/blob/master/SymSpell/frequency_dictionary_en_82_765.txt
# O usar un diccionario en español (se puede generar desde corpus).

_symspell = None

def obtener_symspell() -> SymSpell:
    """Carga y cachea la instancia de SymSpell con el diccionario en español."""
    global _symspell
    if _symspell is None:
        _symspell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
        if os.path.exists(SYMSPELL_PATH):
            _symspell.load_dictionary(SYMSPELL_PATH, term_index=0, count_index=1)
            logger.info(f"Diccionario SymSpell cargado desde {SYMSPELL_PATH}")
        else:
            logger.warning(f"No se encontró diccionario en {SYMSPELL_PATH}. La corrección ortográfica estará deshabilitada.")
    return _symspell

# =============================================================================
# Funciones de normalización
# =============================================================================
def normalizar_texto(texto: str) -> str:
    """
    Elimina tildes, convierte a minúsculas y elimina caracteres especiales.
    """
    if not texto:
        return ""
    texto = texto.lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    # Eliminar caracteres no alfanuméricos (excepto espacios)
    texto = re.sub(r'[^a-z0-9\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def corregir_ortografia(texto: str) -> str:
    """
    Corrige errores ortográficos usando SymSpell.
    """
    if not texto:
        return texto
    symspell = obtener_symspell()
    if symspell is None:
        return texto
    # Dividir en palabras y corregir cada una
    palabras = texto.split()
    palabras_corregidas = []
    for palabra in palabras:
        suggestions = symspell.lookup(palabra, Verbosity.Closest, max_edit_distance=2)
        if suggestions:
            palabras_corregidas.append(suggestions[0].term)
        else:
            palabras_corregidas.append(palabra)
    return " ".join(palabras_corregidas)

def normalizar_y_corregir(texto: str) -> str:
    """
    Aplica normalización y corrección ortográfica completa.
    """
    if not texto:
        return ""
    texto_norm = normalizar_texto(texto)
    texto_corr = corregir_ortografia(texto_norm)
    return texto_corr

# =============================================================================
# Fuzzy matching para entidades
# =============================================================================
def buscar_coincidencia_fuzzy(texto: str, lista_referencia: List[str], umbral: float = 0.75) -> Optional[str]:
    """
    Busca la mejor coincidencia en una lista usando fuzzy matching.
    Retorna el elemento de la lista que mejor coincide, o None si no supera el umbral.
    """
    if not texto or not lista_referencia:
        return None
    texto_norm = normalizar_texto(texto)
    # Usar rapidfuzz para comparar
    resultados = process.extract(texto_norm, lista_referencia, scorer=fuzz.token_set_ratio, limit=1)
    if resultados and resultados[0][1] >= umbral * 100:
        return resultados[0][0]
    return None

def buscar_entidad_en_json(texto: str, json_data: Dict[str, Any], key_lista: str = "nombre", aliases_key: str = "aliases", umbral: float = 0.75) -> Optional[Dict[str, Any]]:
    """
    Busca una entidad en un JSON (ej. catalog_ontology, departamento_municipio) usando fuzzy matching
    sobre el nombre y los aliases.
    """
    if not texto or not json_data:
        return None
    texto_norm = normalizar_texto(texto)
    mejor_item = None
    mejor_score = 0.0
    for item_id, item in json_data.items():
        if isinstance(item, dict):
            # Comparar con el nombre principal
            nombre = item.get(key_lista, "")
            if nombre:
                score = fuzz.token_set_ratio(texto_norm, normalizar_texto(nombre)) / 100.0
                if score > mejor_score:
                    mejor_score = score
                    mejor_item = item
            # Comparar con aliases (si existen)
            aliases = item.get(aliases_key, [])
            for alias in aliases:
                if alias:
                    score = fuzz.token_set_ratio(texto_norm, normalizar_texto(alias)) / 100.0
                    if score > mejor_score:
                        mejor_score = score
                        mejor_item = item
    if mejor_item and mejor_score >= umbral:
        return mejor_item
    return None

def extraer_whatsapp_normalizado(mensaje: str) -> Optional[str]:
    """
    Extrae número de WhatsApp usando regex y lo normaliza.
    """
    # Usar el mismo regex que en api.py (o mejorado)
    match = re.search(r"(\+?[0-9]{1,3}[-.\s]?)?[0-9][\s\-\.]?[0-9]{3,4}[\s\-\.]?[0-9]{3,4}", mensaje)
    if match:
        numero = re.sub(r'[\s\-\.]', '', match.group(0))
        if numero.startswith('+'):
            return numero
        elif len(numero) == 8:
            return f"+502 {numero[:4]}-{numero[4:]}"
        elif len(numero) == 11 and numero.startswith('502'):
            return f"+{numero[:3]} {numero[3:7]}-{numero[7:]}"
        else:
            return f"+502 {numero}"
    return None

def extraer_nombre_con_regex(mensaje: str) -> Optional[str]:
    """
    Extrae nombre usando regex mejorado con normalización.
    """
    # Buscar patrones comunes
    patrones = [
        r"(?:me llamo|soy|mi nombre es|nombre:|llamo)\s*([A-Za-záéíóúñ\s]+)",
        r"^(?:hola|buenas|saludos)\s*(?:soy|me llamo)?\s*([A-Za-záéíóúñ\s]+?)(?:\s*(?:de|mi|que|para|por|es|tengo|quiero|necesito|me|el|la|los|las|un|una|al|con|sin|por|para|como|donde|cuando|cuanto|quien|que|si|no|yo|tu|el|ella|usted|nosotros|vosotros|ellos))",
        r"([A-Za-záéíóúñ]{2,}\s+[A-Za-záéíóúñ]{2,})"
    ]
    for patron in patrones:
        match = re.search(patron, mensaje, re.IGNORECASE)
        if match:
            nombre = match.group(1).strip().title()
            if len(nombre.split()) >= 1:
                return nombre
    return None

def pipeline_extraccion(mensaje: str, 
                        json_ubicacion: Dict[str, Any], 
                        json_productos: Dict[str, Any],
                        json_vendedores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pipeline completo de extracción de datos: normaliza, corrige, y extrae:
    - nombre
    - whatsapp
    - ubicacion (label)
    - productos (lista de nombres)
    - vendedor (email)
    - topologia (On-Grid/Off-Grid)
    - email
    """
    resultado = {}
    if not mensaje:
        return resultado

    # 1. Normalizar y corregir el mensaje completo
    mensaje_procesado = normalizar_y_corregir(mensaje)
    # También guardamos el original para ciertas búsquedas (ej. topología con keywords)
    mensaje_original = mensaje.lower()

    # 2. Extraer nombre (usar regex primero, luego fuzzy si falla)
    nombre = extraer_nombre_con_regex(mensaje_procesado)
    if not nombre:
        # Intentar con el mensaje original sin normalizar (por si el regex captura mejor)
        nombre = extraer_nombre_con_regex(mensaje)
    resultado["nombre"] = nombre

    # 3. Extraer WhatsApp
    whatsapp = extraer_whatsapp_normalizado(mensaje)
    resultado["whatsapp"] = whatsapp

    # 4. Extraer email (regex simple)
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", mensaje)
    resultado["email"] = email_match.group(0) if email_match else None

    # 5. Extraer ubicación (fuzzy contra JSON de municipios)
    ubicacion_item = buscar_entidad_en_json(mensaje_procesado, json_ubicacion, key_lista="label", aliases_key="aliases", umbral=0.7)
    if ubicacion_item:
        resultado["ubicacion_label"] = ubicacion_item.get("label")
        resultado["municipio"] = ubicacion_item.get("municipio")
        resultado["departamento"] = ubicacion_item.get("departamento")
    else:
        # Intentar con el mensaje original sin normalizar
        ubicacion_item = buscar_entidad_en_json(mensaje, json_ubicacion, key_lista="label", aliases_key="aliases", umbral=0.7)
        if ubicacion_item:
            resultado["ubicacion_label"] = ubicacion_item.get("label")
            resultado["municipio"] = ubicacion_item.get("municipio")
            resultado["departamento"] = ubicacion_item.get("departamento")

    # 6. Extraer productos (fuzzy contra catalog_ontology.json)
    productos_encontrados = []
    # Crear lista de nombres y keywords para comparar
    lista_productos = []
    for item in json_productos.values():
        if isinstance(item, dict) and "nombre" in item:
            lista_productos.append(item["nombre"])
            # Añadir keywords como elementos separados para mejorar matching
            for kw in item.get("keywords", []):
                if kw not in lista_productos:
                    lista_productos.append(kw)
    # Buscar coincidencia fuzzy en el mensaje procesado
    mejor_match = buscar_coincidencia_fuzzy(mensaje_procesado, lista_productos, umbral=0.7)
    if mejor_match:
        # Encontrar el item completo
        for item in json_productos.values():
            if isinstance(item, dict) and (item["nombre"] == mejor_match or mejor_match in item.get("keywords", [])):
                if item["nombre"] not in productos_encontrados:
                    productos_encontrados.append(item["nombre"])
                break
    # Si no se encontró, intentar con el mensaje original
    if not productos_encontrados:
        mejor_match = buscar_coincidencia_fuzzy(mensaje, lista_productos, umbral=0.7)
        if mejor_match:
            for item in json_productos.values():
                if isinstance(item, dict) and (item["nombre"] == mejor_match or mejor_match in item.get("keywords", [])):
                    if item["nombre"] not in productos_encontrados:
                        productos_encontrados.append(item["nombre"])
                    break
    resultado["productos"] = productos_encontrados

    # 7. Extraer vendedor (fuzzy contra lista de vendedores)
    vendedor_nombres = [v.get("nombre", "") for v in json_vendedores if v.get("nombre")]
    vendedor_match = buscar_coincidencia_fuzzy(mensaje_procesado, vendedor_nombres, umbral=0.7)
    if not vendedor_match:
        vendedor_match = buscar_coincidencia_fuzzy(mensaje, vendedor_nombres, umbral=0.7)
    if vendedor_match:
        for v in json_vendedores:
            if v.get("nombre") == vendedor_match:
                resultado["vendedor"] = v.get("email")
                break

    # 8. Topología (keywords)
    if any(k in mensaje_original for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
        resultado["topologia"] = "On-Grid"
        resultado["requiere_auditoria_electrica"] = True
    elif any(k in mensaje_original for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
        resultado["topologia"] = "Off-Grid"
        resultado["requiere_auditoria_electrica"] = True

    return resultado
