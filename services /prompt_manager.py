"""
services/prompt_manager.py - Gestión de prompts sin hardcode en código.
VERSIÓN 2.0 – Carga desde prompts.json y/o Langfuse.
"""
import os
import json
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
# CONFIGURACIÓN
# =============================================================================
PROMPTS_JSON_PATH = os.getenv("PROMPTS_JSON_PATH", "config/prompts.json")
USE_LANGFUSE_PROMPTS = os.getenv("USE_LANGFUSE_PROMPTS", "true").lower() == "true"

# =============================================================================
# CARGA LOCAL DESDE JSON (FALLBACK)
# =============================================================================
def load_prompts_from_json() -> Dict[str, str]:
    try:
        with open(PROMPTS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {name: item["content"] for name, item in data.items()}
    except Exception as e:
        logger.error(f"Error cargando prompts desde {PROMPTS_JSON_PATH}: {e}")
        return {}

_LOCAL_PROMPTS = load_prompts_from_json()


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
            logger.info("PromptManager: Usando solo fuente local (JSON)")

    def get_prompt(self, name: str, version: Optional[int] = None) -> Dict[str, Any]:
        cache_key = f"{name}:{version or 'latest'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        content = None
        source = "local"

        if self._client and USE_LANGFUSE_PROMPTS:
            try:
                prompt = self._client.get_prompt(name, version=version)
                if prompt:
                    content = prompt.prompt
                    source = "langfuse"
            except Exception as e:
                logger.warning(f"Langfuse falló para '{name}': {e}")

        if content is None:
            content = _LOCAL_PROMPTS.get(name)
            if content is None:
                raise ValueError(f"Prompt '{name}' no encontrado ni en Langfuse ni en JSON")
            source = "local"

        result = {"content": content, "source": source}
        self._cache[cache_key] = result
        logger.debug(f"PromptManager: '{name}' desde {source}")
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
