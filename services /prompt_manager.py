"""
services/prompt_manager.py - Gestión de prompts con fallback en código.
VERSIÓN 3.0 – No requiere archivos externos.
"""
import os
import logging
from typing import Optional, Dict, Any
from functools import lru_cache

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

from config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# PROMPTS DE FALLBACK (EN CÓDIGO, SIN ARCHIVOS)
# =============================================================================
FALLBACK_PROMPTS = {
    "jarvi_system_prompt": (
        "Eres Jarvi, Ingeniero de Preventa de AISA Solar. "
        "Siempre trata al cliente de **usted**, de manera formal y profesional. "
        "Utiliza el pronombre 'usted' y conjuga los verbos en tercera persona del singular. "
        "Evita cualquier tono coloquial o de amistad. Mantén una actitud respetuosa y cortés en todo momento.\n\n"
        "Responde con los datos auditados:\n"
        "- Ubicación: {ciudad}\n"
        "- Distribuidora: {empresa_electrica}\n"
        "- Tarifa: GTQ {tarifa_base_gtq} /kWh\n"
        "REGLAS: {regla_datos}\n"
        "ONTOLOGÍA: {ontologia_dinamica}"
    ),
    "jarvi_seleccion_productos": (
        "Para poder recomendarle los productos más adecuados, ¿está usted buscando un **sistema completo** "
        "(incluye paneles, inversor, estructura, cableado, etc.) o un **producto específico** "
        "(ej. solo paneles, solo inversor, baterías)?"
    ),
    "jarvi_extractor_contacto": (
        "Identifica nombre o teléfono. Mensaje: {mensaje}"
    )
}

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
USE_LANGFUSE_PROMPTS = os.getenv("USE_LANGFUSE_PROMPTS", "true").lower() == "true"


# =============================================================================
# CLASE PROMPT MANAGER
# =============================================================================
class PromptManager:
    _instance = None
    _client = None
    _cache: Dict[str, Dict] = {}

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

    def get_prompt(self, name: str, version: Optional[int] = None) -> Dict[str, Any]:
        cache_key = f"{name}:{version or 'latest'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        content = None
        source = "fallback"

        # 1. Intentar desde Langfuse
        if self._client and USE_LANGFUSE_PROMPTS:
            try:
                prompt = self._client.get_prompt(name, version=version)
                if prompt:
                    content = prompt.prompt
                    source = "langfuse"
            except Exception as e:
                logger.warning(f"Langfuse falló para '{name}': {e}")

        # 2. Fallback al código
        if content is None:
            content = FALLBACK_PROMPTS.get(name)
            if content is None:
                raise ValueError(f"Prompt '{name}' no encontrado ni en Langfuse ni en fallback")
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

    def invalidate_cache(self):
        self._cache.clear()
        logger.info("PromptManager: Caché invalidada")


# =============================================================================
# FACADE
# =============================================================================
_pm = None

def get_prompt_manager() -> PromptManager:
    global _pm
    if _pm is None:
        _pm = PromptManager()
    return _pm

def get_prompt(name: str, **kwargs) -> str:
    return get_prompt_manager().compile(name, **kwargs)
