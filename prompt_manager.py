# prompt_manager.py - Gestión de prompts con fallback local y Langfuse
# VERSIÓN 2.5.0 – Regla explícita de fuentes y prompts MICDP.
# 31JUL2026

import os
import logging
from typing import Optional, Dict, Any

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

from config import settings

logger = logging.getLogger(__name__)

FALLBACK_PROMPTS = {
    "jarvi_system_prompt": (
        "Eres Jarvi, Ingeniero de Preventa de AISA Solar. "
        "Siempre trata al cliente de usted, de manera formal y profesional. "
        "Utiliza el pronombre 'usted' y conjuga los verbos en tercera persona del singular. "
        "Evita cualquier tono coloquial o de amistad. Mantén una actitud respetuosa y cortés en todo momento.\n\n"
        "INFORMACIÓN CONOCIDA DEL USUARIO:\n"
        "{conocimiento_usuario}\n\n"
        "REGLAS DE ORO:\n"
        "1. Antes de preguntar cualquier dato, verifica si ya está en el contexto (sección 'INFORMACIÓN CONOCIDA').\n"
        "2. Si el dato ya está disponible, NO lo preguntes. Úsalo para personalizar la respuesta.\n"
        "3. Avanza en la conversación hacia la definición de la necesidad exacta y la recomendación de productos.\n"
        "4. Cuando tengas toda la información necesaria (score >= 60%), activa el cierre comercial: resumen, precio, advertencia, fecha estimada y pregunta sobre vendedor.\n"
        "5. NO sugieras comprar en línea ni visitar la tienda web. El proceso es exclusivamente de preventa: definir necesidad, cotizar y derivar a un vendedor.\n"
        "6. Toda la información técnica debe provenir de la ontología de productos de AISA Solar o del sitio web www.aisa.com.gt. No inventes precios, especificaciones ni datos técnicos.\n"
        "7. NO menciones productos, marcas, precios o especificaciones de otras empresas o fabricantes que no estén en el catálogo de AISA Solar. La única fuente de información externa permitida es www.aisa.com.gt. La fuente interna es la ontología (catalog_ontology.json).\n"
        "8. Si un producto no está en el catálogo, indícalo amablemente y ofrece alternativas del catálogo. No recomiendes productos de otras marcas.\n\n"
        "Datos auditados disponibles:\n"
        "- Ubicación: {ciudad}\n"
        "- Distribuidora: {empresa_electrica}\n"
        "- Tarifa: GTQ {tarifa_base_gtq} /kWh\n"
        "REGLAS DE RECOPILACIÓN: {regla_datos}\n"
        "ONTOLOGÍA DE PRODUCTOS: {ontologia_dinamica}"
    ),
    "jarvi_seleccion_productos": (
        "Para poder recomendarle los productos más adecuados, ¿está usted buscando un sistema completo (incluye paneles, inversor, estructura, cableado, etc.) o un producto específico (ej. solo paneles, solo inversor, baterías)?"
    ),
    "jarvi_extractor_contacto": (
        "Identifica nombre o teléfono. Mensaje: {mensaje}"
    ),
    "jarvi_advertencia_precio": (
        "El precio indicado corresponde únicamente al equipo/producto. No incluye instalación, mano de obra, servicios adicionales ni costos de envío."
    ),
    "jarvi_micdp_welcome": (
        "Bienvenido(a) al Proceso Conversacional para la Definición de Proyectos.\n\n"
        "Este espacio forma parte de una investigación académica orientada al desarrollo de un modelo inteligente para identificar necesidades y apoyar la formulación conceptual de proyectos relacionados con:\n\n"
        "- Energías renovables.\n- Sistemas fotovoltaicos.\n- Refrigeración industrial y doméstica.\n- Cadena de frío.\n- Bombeo de agua.\n- Eficiencia energética.\n- Procesos industriales.\n- Soluciones tecnológicas para hogares, comercios e industrias.\n\n"
        "Su participación es voluntaria y tiene fines exclusivamente académicos, científicos y educativos.\n\n"
        "Durante la conversación, le realizaré preguntas de forma natural para comprender su contexto, sus necesidades, sus objetivos y las condiciones técnicas de su proyecto. No existe un cuestionario fijo; la conversación se adapta a la información que usted proporciona.\n\n"
        "Puede pausar y retomar la entrevista en cualquier momento. El sistema recordará el estado de su proyecto y continuará desde donde quedó.\n\n"
        "¿Listo para comenzar? Solo responda 'Sí' o 'Adelante' cuando esté preparado."
    ),
    "jarvi_micdp_summary_early": (
        "📋 BORRADOR DE PERFIL - PROYECTO {thread_id}\n"
        "(Completitud: {completeness:.0f}%)\n\n"
        "{summary_text}\n\n"
        "📊 VARIABLES PENDIENTES:\n{pendientes}\n\n"
        "🔄 ¿Desea corregir, complementar o confirmar la información presentada?\n"
        "- Responda 'Corregir [dato]' para cambiar un valor.\n"
        "- Responda 'Complementar' para añadir información faltante.\n"
        "- Responda 'Confirmar' si todo es correcto.\n\n"
        "📌 Puede continuar la entrevista respondiendo a las preguntas."
    ),
    "jarvi_micdp_summary_intermediate": (
        "📋 BORRADOR DE PERFIL - PROYECTO {thread_id}\n"
        "(Completitud: {completeness:.0f}%)\n\n"
        "{summary_text}\n\n"
        "📊 VARIABLES PENDIENTES:\n{pendientes}\n\n"
        "🔄 ¿Desea corregir, complementar o confirmar la información presentada?"
    ),
    "jarvi_micdp_summary_advanced": (
        "📋 BORRADOR DE PERFIL - PROYECTO {thread_id}\n"
        "(Completitud: {completeness:.0f}%)\n\n"
        "{summary_text}\n\n"
        "📊 VARIABLES PENDIENTES:\n{pendientes}\n\n"
        "🔄 ¿Desea corregir, complementar o confirmar la información presentada?"
    ),
    "jarvi_micdp_completed": (
        "✅ ¡Proceso completado!\n\n"
        "El perfil de su proyecto ha sido generado satisfactoriamente.\n\n"
        "{profile_text}\n\n"
        "Gracias por su participación en esta investigación académica."
    )
}

USE_LANGFUSE_PROMPTS = os.getenv("USE_LANGFUSE_PROMPTS", "true").lower() == "true"

class PromptManager:
    _instance = None
    _client = None
    _cache = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._setup_client()

    def _setup_client(self):
        if USE_LANGFUSE_PROMPTS and settings.langfuse_public_key:
            try:
                if Langfuse is None:
                    raise ImportError("Langfuse SDK no instalado")
                self._client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host
                )
                logger.info("PromptManager: Cliente Langfuse listo")
            except Exception as e:
                logger.error(f"PromptManager: Error en cliente: {e}")
                self._client = None
        else:
            logger.info("PromptManager: Usando fallback en código")

    def get_prompt(self, name: str, version: Optional[int] = None):
        cache_key = f"{name}:{version or 'latest'}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        content = None
        source = "fallback"
        if self._client and USE_LANGFUSE_PROMPTS:
            try:
                prompt = self._client.get_prompt(name, version=version)
                if prompt:
                    content = prompt.prompt
                    source = "langfuse"
                    logger.debug(f"Prompt '{name}' obtenido de Langfuse")
            except Exception as e:
                logger.warning(f"Langfuse falló para '{name}': {e}")
        if content is None:
            content = FALLBACK_PROMPTS.get(name)
            if content is None:
                logger.error(f"Prompt '{name}' no encontrado en fallback. Usando cadena vacía.")
                content = ""
            source = "fallback"
        result = {"content": content, "source": source}
        self._cache[cache_key] = result
        logger.info(f"PromptManager: '{name}' desde {source}")
        return result

    def compile(self, name: str, **kwargs) -> str:
        data = self.get_prompt(name)
        try:
            return data["content"].format(**kwargs)
        except KeyError as e:
            logger.error(f"Variable faltante en '{name}': {e}")
            return data["content"]

_pm = None

def get_prompt_manager():
    global _pm
    if _pm is None:
        _pm = PromptManager()
    return _pm

def get_prompt(name: str, **kwargs) -> str:
    return get_prompt_manager().compile(name, **kwargs)
