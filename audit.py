"""
audit.py
═══════════════════════════════════════════════════════════════════════
Auditoría y gestión de errores con sanitización de PII (ISO 27001).
VERSIÓN 2.0.04 – Decorador con detección de asincronía.
Eliminada dependencia de Gmail/Correo.
"""
import asyncio
import functools
import json
import logging
import traceback
from datetime import datetime, timezone
from utils.sanitize import sanitize_pii, sanitize_dict

logger = logging.getLogger("JarviAudit")

def auditar_fase(nombre_fase: str, criticidad: str = "ALTA"):
    """
    Decorador homogeneizado para auditoría. Detecta si la función es síncrona o asíncrona
    y la envuelve correctamente. En caso de error, registra en logs con metadata sanitizada.
    """
    def decorator(func):
        # Caso 1: Función Asíncrona (async def)
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    timestamp_error = datetime.now(timezone.utc).isoformat()
                    tb_str = traceback.format_exc()
                    args_sanitized = sanitize_dict(str(args)[:500])
                    kwargs_sanitized = sanitize_dict(str(kwargs)[:500])
                    error_payload = {
                        "fase": nombre_fase,
                        "criticidad": criticidad,
                        "timestamp_utc": timestamp_error,
                        "funcion_origen": func.__name__,
                        "error_tipo": type(e).__name__,
                        "error_mensaje": sanitize_pii(str(e)),
                        "argumentos_posicionales": args_sanitized,
                        "argumentos_llave": kwargs_sanitized
                    }
                    logger.error(f"🚨 [METADATOS AUDITORÍA ISO]: {json.dumps(error_payload, indent=2)}")
                    logger.error(f"📋 [TRACEBACK ORIGINAL]:\n{tb_str}")
                    raise e
            return async_wrapper
        
        # Caso 2: Función Síncrona (def)
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    timestamp_error = datetime.now(timezone.utc).isoformat()
                    tb_str = traceback.format_exc()
                    args_sanitized = sanitize_dict(str(args)[:500])
                    kwargs_sanitized = sanitize_dict(str(kwargs)[:500])
                    error_payload = {
                        "fase": nombre_fase,
                        "criticidad": criticidad,
                        "timestamp_utc": timestamp_error,
                        "funcion_origen": func.__name__,
                        "error_tipo": type(e).__name__,
                        "error_mensaje": sanitize_pii(str(e)),
                        "argumentos_posicionales": args_sanitized,
                        "argumentos_llave": kwargs_sanitized
                    }
                    logger.error(f"🚨 [METADATOS AUDITORÍA ISO]: {json.dumps(error_payload, indent=2)}")
                    logger.error(f"📋 [TRACEBACK ORIGINAL]:\n{tb_str}")
                    raise e
            return sync_wrapper
    return decorator
