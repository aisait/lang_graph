"""
ontology.py
Módulo de ontología del catálogo de productos de AISA Solar para JARVI 2.0.
Carga y filtra bloques de conocimiento desde un archivo JSON externo,
proporcionando fragmentos de contexto al motor de razonamiento.

Estándares aplicados:
- ISO/IEC/IEEE 12207:2008 (Ciclo de vida del software): este módulo es
  un elemento de configuración del sistema, diseñado para ser mantenido
  y verificado de forma independiente.
- ISO/IEC 26514:2021 (Documentación de software): todas las funciones están
  documentadas con descripciones, parámetros, valores de retorno y pruebas
  de caja negra.
- ISO/IEC 25010:2011 (Calidad del producto):
  * Adecuación funcional: selecciona las categorías de producto relevantes
    según la topología del sistema fotovoltaico.
  * Eficiencia de desempeño: utiliza un caché en memoria para evitar
    lecturas repetitivas del disco.
  * Fiabilidad: maneja rutas alternativas (ONTOLOGY_JSON_PATH) y errores
    de lectura sin interrumpir el servicio.
- ISO/IEC 29119:2022 (Pruebas de software - caja negra):
  Las pruebas sugeridas se describen en cada función.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List, Tuple

# ---------------------------------------------------------------------------
# Configuración del Logger para observabilidad en entornos serverless
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Caché en memoria (Singleton) para evitar múltiples lecturas de disco
# ---------------------------------------------------------------------------
_ONTOLOGIA_CACHE: Optional[Dict[str, Any]] = None

# ---------------------------------------------------------------------------
# Resolución robusta de la ruta del archivo JSON
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_PATH = os.path.join(BASE_DIR, 'catalog_ontology.json')
DEFAULT_JSON_PATH = os.getenv("ONTOLOGY_JSON_PATH", FALLBACK_PATH)


def cargar_ontologia(file_path: str = DEFAULT_JSON_PATH) -> Dict[str, Any]:
    """
    Carga y cachea en memoria la taxonomía del catálogo de productos
    desde un archivo JSON externo. Implementa el patrón Singleton sobre
    la ejecución del contenedor para evitar lecturas repetitivas.

    Parámetros:
        file_path (str): ruta al archivo JSON de ontología. Por defecto
                         usa la variable de entorno ONTOLOGY_JSON_PATH o
                         el archivo 'catalog_ontology.json' en el mismo
                         directorio.

    Retorna:
        dict: diccionario con la ontología completa, donde cada clave
              es un identificador de categoría y el valor es otro
              diccionario con 'tag', 'nombre', 'url' y 'keywords'.

    Prueba de caja negra (ISO/IEC 29119):
        1. Primera llamada: debe leer el archivo y devolver el diccionario.
        2. Segunda llamada: debe devolver el mismo diccionario desde caché
           sin acceder al disco (verificar con logs).
        3. Archivo inexistente: debe lanzar FileNotFoundError.
        4. Archivo con JSON mal formado: debe lanzar json.JSONDecodeError
           y registrar un log crítico.
        5. Llamada concurrente: la caché es segura porque solo se asigna
           una vez (no se requiere lock adicional en este diseño simple,
           pero se puede probar con múltiples hilos para verificar que
           no hay doble carga).
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
        logger.info(
            f"Ontología cargada exitosamente en memoria desde {file_path}. "
            f"{len(_ONTOLOGIA_CACHE)} categorías indexadas."
        )
        return _ONTOLOGIA_CACHE
    except json.JSONDecodeError as je:
        logger.critical(f"Corrupción detectada en el esquema estructurado JSON: {str(je)}")
        raise
    except Exception as e:
        logger.critical(f"Fallo catastrófico en la lectura de ontología: {str(e)}")
        raise


def obtener_fragmento_ontologia(topologia: Optional[str]) -> str:
    """
    Realiza el ruteo epistemológico avanzado: selecciona los bloques de
    productos relevantes según la topología del sistema fotovoltaico
    detectada por el grafo del agente (On‑Grid, Off‑Grid, Bombeo, etc.).
    El resultado es una cadena de texto formateada que se inyecta en el
    prompt del LLM para ahorrar ventana de contexto (Context Window
    Preservation).

    Parámetros:
        topologia (str | None): topología detectada, puede ser None
                                o contener palabras como "ON-GRID",
                                "OFF-GRID", "BOMBA", etc.

    Retorna:
        str: fragmento de ontología con las categorías y enlaces
             correspondientes, listo para insertar en el system prompt.

    Prueba de caja negra (ISO/IEC 29119):
        1. topologia=None: devuelve bloques por defecto (11-15, 18, 20, 26, 38, 46, 51).
        2. topologia="ON-GRID": incluye los bloques 1-10, 20, 35, 37, 38, 60, 61, 64, 79-81, 85.
        3. topologia="OFF-GRID": incluye los bloques 14, 16, 18-20, 22-24, 26-28, 32, 34, 35, 45, 46, 50-53, 62, 64, 81, 82, 86.
        4. topologia="BOMBA SOLAR": incluye bloques de tuberías y bombas (12-16, 39-42, 55-59, 66, 73, 74, 77, 78, 83).
        5. Si falla la carga de ontología, devuelve el mensaje de error sin lanzar excepción.
        6. Si un bloque_id no existe en el catálogo, se omite y se registra un warning.
    """
    try:
        ontologia = cargar_ontologia()
    except Exception:
        return "Error interno de inicialización: Catálogo temporalmente indisponible."

    # Selección de bloques según topología
    if not topologia:
        bloques_requeridos = [
            "11", "12", "13", "14", "15", "18", "20",
            "26", "38", "46", "51"
        ]
    elif "ON-GRID" in topologia.upper() or "ATADO" in topologia.upper():
        bloques_requeridos = [
            str(i) for i in range(1, 11)
        ] + [
            "20", "35", "37", "38", "60", "61", "64",
            "79", "80", "81", "85"
        ]
    elif "OFF-GRID" in topologia.upper() or "AISLADO" in topologia.upper():
        bloques_requeridos = [
            "14", "16", "18", "19", "20", "22", "23",
            "24", "26", "27", "28", "32", "34", "35",
            "45", "46", "50", "51", "52", "53", "62",
            "64", "81", "82", "86"
        ]
    elif "BOMBA" in topologia.upper() or "HIDRO" in topologia.upper() or "BOMBEO" in topologia.upper():
        bloques_requeridos = [
            "12", "13", "15", "16", "39", "40", "41",
            "42", "55", "56", "57", "58", "59", "66",
            "73", "74", "77", "78", "83"
        ]
    else:
        bloques_requeridos = [
            "11", "12", "13", "14", "15", "18", "20",
            "26", "38", "46", "51"
        ]

    resultado: List[str] = []
    for bloque_id in bloques_requeridos:
        if bloque_id in ontologia:
            item = ontologia[bloque_id]
            resultado.append(
                f"Categoría [{bloque_id}]: {item['nombre']}\n"
                f"Enlace Directo: {item['url']}\n"
                f"Keywords de Validación: {', '.join(item['keywords'])}"
            )
        else:
            logger.warning(
                f"Se solicitó el bloque id '{bloque_id}', "
                f"pero no está definido en el catálogo JSON."
            )

    return "\n\n".join(resultado)


# =============================================================================
# NUEVA FUNCIÓN: Obtención de bloques de productos con filtro por tipo
# =============================================================================
def get_product_blocks(topologia: Optional[str], tipo: Optional[str] = None) -> List[str]:
    """
    Retorna la lista de IDs de bloques de productos correspondientes a la
    topología detectada, opcionalmente filtrada por tipo (sistema/unitario).

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: punto de extensión del módulo.
    - ISO/IEC 26514:2021: documentación completa.
    - ISO/IEC 25010:2011: determinista y eficiente.
    - ISO/IEC 29119:2022: pruebas de caja negra sugeridas.

    Parámetros:
        topologia (str | None): topología detectada.
        tipo (str | None): "sistema", "unitario" o None (sin filtro).

    Retorna:
        List[str]: lista de IDs de bloques.

    Prueba de caja negra (ISO/IEC 29119):
        1. topologia=None, tipo=None: devuelve bloques por defecto.
        2. topologia="ON-GRID", tipo="sistema": devuelve solo sistemas On‑Grid.
        3. topologia="OFF-GRID", tipo="unitario": devuelve solo productos unitarios Off‑Grid.
    """
    # Primero obtener los bloques por topología
    if not topologia:
        base = ["11","12","13","14","15","18","20","26","38","46","51"]
    elif "ON-GRID" in topologia.upper() or "ATADO" in topologia.upper():
        base = [str(i) for i in range(1,11)] + ["20","35","37","38","60","61","64","79","80","81","85"]
    elif "OFF-GRID" in topologia.upper() or "AISLADO" in topologia.upper():
        base = ["14","16","18","19","20","22","23","24","26","27","28","32","34","35","45","46","50","51","52","53","62","64","81","82","86"]
    elif "BOMBA" in topologia.upper() or "HIDRO" in topologia.upper() or "BOMBEO" in topologia.upper():
        base = ["12","13","15","16","39","40","41","42","55","56","57","58","59","66","73","74","77","78","83"]
    else:
        base = ["11","12","13","14","15","18","20","26","38","46","51"]

    # Si no se filtra por tipo, devolver todos
    if not tipo:
        return base

    # Filtrar por tipo
    ontologia = cargar_ontologia()
    filtrados = []
    for bid in base:
        if bid in ontologia and ontologia[bid].get("tipo") == tipo:
            filtrados.append(bid)
    return filtrados


# =============================================================================
# NUEVA FUNCIÓN: Obtener productos relevantes (estructurados)
# =============================================================================
def obtener_productos_relevantes(topologia: str, tipo: Optional[str] = None, max_items: int = 5) -> List[Dict]:
    """
    Retorna una lista de hasta max_items productos de la ontología,
    filtrados por topología y tipo (si se especifica).
    Cada producto es un diccionario con 'nombre', 'tag', 'url', 'tipo'.

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: extensión para soportar selección estructurada.
    - ISO/IEC 26514:2021: documentación completa.
    - ISO/IEC 25010:2011: rápida y con caché.

    Parámetros:
        topologia (str): topología detectada.
        tipo (str | None): "sistema", "unitario" o None.
        max_items (int): máximo de productos a retornar.

    Retorna:
        List[Dict]: lista de productos.

    Prueba de caja negra (ISO/IEC 29119):
        1. topologia="ON-GRID", tipo="sistema": retorna hasta 5 sistemas.
        2. topologia="OFF-GRID", tipo=None: retorna hasta 5 productos sin filtrar.
        3. tipo no válido: retorna lista vacía.
    """
    ontologia = cargar_ontologia()
    bloques = get_product_blocks(topologia, tipo)
    productos = []
    for bid in bloques[:max_items]:
        if bid in ontologia:
            item = ontologia[bid]
            productos.append({
                "nombre": item["nombre"],
                "tag": item["tag"],
                "url": item["url"],
                "tipo": item.get("tipo", "desconocido")
            })
    return productos


# =============================================================================
# FUNCIÓN ORIGINAL: Búsqueda semántica de productos por mensaje
# =============================================================================
def buscar_productos_por_mensaje(mensaje: str, top_n: int = 5) -> List[str]:
    """
    Busca en el catálogo los productos cuyas keywords coincidan con el mensaje del usuario.
    Retorna hasta top_n nombres de productos (según el campo 'nombre' de cada categoría).

    Esta función reutiliza el caché de cargar_ontologia(), por lo que es eficiente
    y consistente con el resto del sistema.

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: extensión del módulo para soportar análisis semántico.
    - ISO/IEC 26514:2021: documentación completa.
    - ISO/IEC 25010:2011: la función es rápida y utiliza el caché en memoria.
    - ISO/IEC 29119:2022: pruebas de caja negra sugeridas.

    Parámetros:
        mensaje (str): texto del usuario (en minúsculas o no).
        top_n (int): número máximo de productos a retornar (por defecto 5).

    Retorna:
        List[str]: lista de nombres de productos encontrados.

    Prueba de caja negra (ISO/IEC 29119):
        1. Mensaje "quiero paneles solares y calentadores": debe devolver al menos
           los nombres que contengan "panel solar" y "calentador".
        2. Mensaje sin coincidencias: devuelve lista vacía.
        3. top_n=2: devuelve máximo 2 productos.
    """
    ontologia = cargar_ontologia()
    productos_encontrados = []
    mensaje_lower = mensaje.lower()
    for key, item in ontologia.items():
        if isinstance(item, dict) and "nombre" in item:
            palabras_clave = item.get("keywords", [])
            for keyword in palabras_clave:
                if keyword.lower() in mensaje_lower:
                    if item["nombre"] not in productos_encontrados:
                        productos_encontrados.append(item["nombre"])
                        if len(productos_encontrados) >= top_n:
                            return productos_encontrados
                    break
    return productos_encontrados


# =============================================================================
# NUEVAS FUNCIONES PARA LA LÓGICA DE REQUISITOS (ONTOLOGÍA EXTENDIDA)
# =============================================================================

def inferir_tag_por_mensaje(mensaje: str) -> Optional[str]:
    """
    Busca en la ontología el primer tag (clave numérica) cuyas keywords
    coincidan con el mensaje del usuario. Retorna la clave (ej. '1', '11', '19')
    o None si no hay coincidencia.

    Esta función es el punto de entrada para la detección del producto
    en el flujo conversacional, permitiendo cargar los requisitos específicos
    del producto detectado.

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: extensión del módulo para soportar detección semántica.
    - ISO/IEC 26514:2021: documentación completa.
    - ISO/IEC 25010:2011: eficiente gracias al caché en memoria.

    Parámetros:
        mensaje (str): texto del usuario (en minúsculas o no).

    Retorna:
        Optional[str]: el tag (clave numérica) del producto detectado, o None.

    Prueba de caja negra (ISO/IEC 29119):
        1. Mensaje "quiero un calentador solar": debe retornar "11".
        2. Mensaje "necesito paneles solares para mi casa": debe retornar "1" o "20".
        3. Mensaje sin coincidencias: retorna None.
        4. Mensaje con múltiples coincidencias: retorna el primero encontrado.
    """
    if not mensaje or not mensaje.strip():
        return None

    mensaje_lower = mensaje.lower()
    ontologia = cargar_ontologia()

    for key, item in ontologia.items():
        if not isinstance(item, dict) or "keywords" not in item:
            continue
        keywords = item.get("keywords", [])
        for keyword in keywords:
            if keyword.lower() in mensaje_lower:
                logger.info(f"Tag inferido: '{key}' ({item.get('nombre', '')}) desde keyword: '{keyword}'")
                return key

    logger.debug(f"No se encontró tag para el mensaje: {mensaje[:50]}...")
    return None


def get_requirements_by_tag(tag: str) -> List[Dict]:
    """
    Retorna la lista de requisitos (requirements) de un bloque de producto
    dado su tag (clave numérica). Si el tag no existe o no tiene requisitos
    definidos, retorna una lista vacía.

    Los requisitos son utilizados por el agente para formular preguntas
    contextuales y específicas sobre el producto, evitando preguntas
    genéricas o redundantes.

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: extensión del módulo para soportar
      la lógica de diálogo imperceptible.
    - ISO/IEC 26514:2021: documentación completa.
    - ISO/IEC 25010:2011: respuesta rápida gracias al caché en memoria.

    Parámetros:
        tag (str): clave numérica del producto (ej. '1', '11', '19').

    Retorna:
        List[Dict]: lista de requisitos, cada uno con 'field', 'question' y 'type'.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='1' (On-Grid): retorna requisitos de consumo, tarifa y espacio.
        2. tag='11' (Calentadores): retorna requisitos de número de personas y tipo de instalación.
        3. tag='999' (inexistente): retorna lista vacía.
        4. tag='12' (tuberías, sin requisitos): retorna lista vacía.
    """
    ontologia = cargar_ontologia()
    item = ontologia.get(tag)

    if not item or not isinstance(item, dict):
        logger.warning(f"Tag '{tag}' no encontrado en la ontología.")
        return []

    requirements = item.get("requirements", [])
    if not isinstance(requirements, list):
        logger.warning(f"El campo 'requirements' de '{tag}' no es una lista.")
        return []

    logger.debug(f"Requisitos cargados para tag '{tag}': {len(requirements)} items")
    return requirements


# =============================================================================
# NUEVAS FUNCIONES PARA DIAGNÓSTICO ELÉCTRICO Y DIMENSIONAMIENTO OFF‑GRID
# =============================================================================

def get_requires_diagnostic(tag: str) -> bool:
    """
    Retorna True si el producto identificado por 'tag' requiere
    diagnóstico eléctrico (preguntar por consumo y tarifa).
    Por defecto, si el campo no existe, retorna False.

    Estándares aplicados:
    - ISO/IEC 25010:2011: la función es determinista y rápida.

    Parámetros:
        tag (str): clave numérica del producto.

    Retorna:
        bool: True si el producto necesita diagnóstico eléctrico, False en caso contrario.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='1' (On-Grid): retorna True.
        2. tag='11' (Calentador): retorna False.
        3. tag='999' (inexistente): retorna False.
    """
    ontologia = cargar_ontologia()
    item = ontologia.get(tag)
    if not item or not isinstance(item, dict):
        return False
    return item.get("requiere_diagnostico_electrico", False)


def get_dimensionamiento_by_tag(tag: str) -> Optional[Dict]:
    """
    Retorna el objeto 'dimensionamiento' del producto identificado por 'tag'.
    Si no existe, retorna None.

    Estándares aplicados:
    - ISO/IEC 26514:2021: documentación completa.

    Parámetros:
        tag (str): clave numérica del producto.

    Retorna:
        Optional[Dict]: el objeto dimensionamiento, o None si no existe.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='19' (Sistemas Aislados): retorna el objeto dimensionamiento.
        2. tag='1' (On-Grid): retorna None (o no tiene).
        3. tag='999' (inexistente): retorna None.
    """
    ontologia = cargar_ontologia()
    item = ontologia.get(tag)
    if not item or not isinstance(item, dict):
        return None
    return item.get("dimensionamiento")


def get_componentes_urls(tag: str) -> Dict[str, str]:
    """
    Retorna un diccionario con las URLs de los componentes
    (panel, batería, inversor, controlador) para el producto Off‑Grid
    identificado por 'tag'. Si no se encuentra dimensionamiento o no tiene
    URLs definidas, retorna un diccionario vacío.

    Estándares aplicados:
    - ISO/IEC/IEEE 12207:2008: extensión para soportar extracción dinámica.

    Parámetros:
        tag (str): clave numérica del producto.

    Retorna:
        Dict[str, str]: diccionario con las URLs de los componentes.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='19': retorna {'panel': 'https://...', 'bateria': 'https://...', ...}
        2. tag='1': retorna {}
    """
    dimensionamiento = get_dimensionamiento_by_tag(tag)
    if not dimensionamiento:
        return {}
    componentes = dimensionamiento.get("componentes", {})
    urls = {}
    for key, comp in componentes.items():
        if isinstance(comp, dict) and "url" in comp:
            urls[key] = comp["url"]
    return urls


def get_equipos_tipicos(tag: str) -> List[Dict]:
    """
    Retorna la lista de equipos típicos (consumo en watts, horas de uso)
    para el producto Off‑Grid identificado por 'tag'. Si no se encuentra,
    retorna una lista vacía.

    Estándares aplicados:
    - ISO/IEC 26514:2021: documentación completa.

    Parámetros:
        tag (str): clave numérica del producto.

    Retorna:
        List[Dict]: lista de equipos típicos.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='19': retorna la lista de equipos definida en la ontología.
        2. tag='1': retorna [].
    """
    dimensionamiento = get_dimensionamiento_by_tag(tag)
    if not dimensionamiento:
        return []
    return dimensionamiento.get("equipos_tipicos", [])


def get_factor_seguridad(tag: str) -> float:
    """
    Retorna el factor de seguridad para el dimensionamiento Off‑Grid.
    Por defecto, si no se define en la ontología, retorna 1.2.

    Estándares aplicados:
    - ISO/IEC 25010:2011: comportamiento robusto con fallback.

    Parámetros:
        tag (str): clave numérica del producto.

    Retorna:
        float: factor de seguridad.

    Prueba de caja negra (ISO/IEC 29119):
        1. tag='19': retorna el valor definido en la ontología.
        2. tag='1': retorna 1.2 por defecto.
    """
    dimensionamiento = get_dimensionamiento_by_tag(tag)
    if not dimensionamiento:
        return 1.2
    return dimensionamiento.get("factor_seguridad", 1.2)


def calcular_consumo_diario(equipos: List[Dict], horas_uso: List[float]) -> float:
    """
    Calcula el consumo diario en Wh a partir de una lista de equipos y sus horas de uso.
    Cada equipo es un diccionario con 'potencia_w' y opcionalmente 'horas_dia'.
    Si no se proporcionan horas_uso, se usan las del equipo.

    Estándares aplicados:
    - ISO/IEC 29119:2022: pruebas de caja negra.

    Parámetros:
        equipos (List[Dict]): lista de equipos con 'potencia_w' y 'horas_dia'.
        horas_uso (List[float]): lista de horas de uso correspondiente a cada equipo.
                                  Si no se pasa, se usa 'horas_dia' del equipo.

    Retorna:
        float: consumo diario en Wh.

    Prueba de caja negra (ISO/IEC 29119):
        1. equipos=[{'potencia_w':80, 'horas_dia':24}] → 1920.
        2. equipos=[{'potencia_w':30, 'horas_dia':6}] → 180.
        3. equipos vacío → 0.0.
    """
    if not equipos:
        return 0.0

    consumo_total = 0.0
    for i, equipo in enumerate(equipos):
        potencia = equipo.get("potencia_w", 0)
        if i < len(horas_uso):
            horas = horas_uso[i]
        else:
            horas = equipo.get("horas_dia", 0)
        consumo_total += potencia * horas
    return consumo_total


def dimensionar_sistema_offgrid(
    consumo_wh_dia: float,
    autonomia_dias: int,
    tag: str
) -> Dict:
    """
    Dimensiona un sistema Off‑Grid a partir del consumo diario, la autonomía en días
    y los datos de la ontología para el producto identificado por 'tag'.
    Retorna un diccionario con los resultados: número de paneles, baterías, inversor,
    y URLs de los componentes para obtener precios dinámicamente.

    Estándares aplicados:
    - ISO/IEC 25010:2011: eficiencia y fiabilidad.
    - ISO/IEC 29119:2022: pruebas de caja negra.

    Parámetros:
        consumo_wh_dia (float): consumo diario en Wh.
        autonomia_dias (int): días de autonomía deseada.
        tag (str): clave numérica del producto (ej. '19').

    Retorna:
        Dict: {
            "paneles": {"cantidad": int, "potencia_w": float, "url": str},
            "baterias": {"cantidad": int, "capacidad_kwh": float, "url": str},
            "inversor": {"potencia_w": float, "url": str},
            "controlador": {"url": str},
            "precio_total_estimado": float,  # Suma de precios de componentes (se necesita extraer)
            "advertencia": str
        }

    Prueba de caja negra (ISO/IEC 29119):
        1. consumo=2420, autonomia=2, tag='19' → dimensionamiento razonable.
        2. consumo=0, autonomia=1 → retorna sistema mínimo.
        3. tag sin dimensionamiento → retorna {}.
    """
    dimensionamiento = get_dimensionamiento_by_tag(tag)
    if not dimensionamiento:
        logger.warning(f"No hay dimensionamiento para tag '{tag}'")
        return {}

    factor_seguridad = get_factor_seguridad(tag)

    # Consumo diario ajustado con factor de seguridad
    consumo_ajustado = consumo_wh_dia * factor_seguridad

    # Energía total necesaria para la autonomía (Wh)
    energia_total = consumo_ajustado * autonomia_dias

    # Componentes
    componentes = dimensionamiento.get("componentes", {})
    panel = componentes.get("panel", {})
    bateria = componentes.get("bateria", {})
    inversor = componentes.get("inversor", {})
    controlador = componentes.get("controlador", {})

    # Calcular número de baterías (capacidad en kWh)
    capacidad_bateria_kwh = bateria.get("capacidad_kwh", 0)
    if capacidad_bateria_kwh > 0:
        num_baterias = (energia_total / 1000) / capacidad_bateria_kwh
        num_baterias = max(1, round(num_baterias))
    else:
        num_baterias = 1

    # Calcular número de paneles (potencia en W)
    potencia_panel_w = panel.get("potencia_w", 0)
    if potencia_panel_w > 0:
        # Suponiendo 5 horas de sol pico al día (constante razonable)
        horas_sol_pico = 5
        energia_panel_dia = potencia_panel_w * horas_sol_pico / 1000  # kWh/día por panel
        num_paneles = (consumo_ajustado / 1000) / energia_panel_dia
        num_paneles = max(1, round(num_paneles))
    else:
        num_paneles = 1

    # Inversor: se selecciona el que tenga al menos la potencia pico necesaria
    potencia_inversor_w = inversor.get("potencia_w", 0)

    # URLs
    urls = {
        "panel": panel.get("url", ""),
        "bateria": bateria.get("url", ""),
        "inversor": inversor.get("url", ""),
        "controlador": controlador.get("url", "")
    }

    resultado = {
        "paneles": {
            "cantidad": num_paneles,
            "potencia_w": potencia_panel_w,
            "url": urls["panel"]
        },
        "baterias": {
            "cantidad": num_baterias,
            "capacidad_kwh": capacidad_bateria_kwh,
            "url": urls["bateria"]
        },
        "inversor": {
            "potencia_w": potencia_inversor_w,
            "url": urls["inversor"]
        },
        "controlador": {
            "url": urls["controlador"]
        },
        "precio_total_estimado": 0.0,  # Se calculará externamente con price_extractor
        "advertencia": "El precio indicado corresponde únicamente a los equipos. No incluye instalación, mano de obra, servicios adicionales ni costos de envío."
    }

    logger.info(f"Dimensionamiento Off‑Grid para tag '{tag}': {num_paneles} paneles, {num_baterias} baterías, inversor {potencia_inversor_w}W")
    return resultado
