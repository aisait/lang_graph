"""
utils/sanitize.py
═══════════════════════════════════════════════════════════════════════
Sanitización de datos personales (PII) conforme ISO/IEC 27001:2022 A.8.2.
Cumple con el principio de privacidad por diseño (GDPR).

Funcionalidades:
    - Sanitizar emails, teléfonos (Guatemala e internacional), DPI, tarjetas de crédito.
    - Sanitización recursiva de diccionarios y listas.

Pruebas de caja negra (ISO/IEC 29119):
    BC‑T11: Enviar mensaje con PII → verificar que se redacte antes de guardar.
    BC‑T12: Sanitizar diccionario anidado → todos los strings sensibles redactados.
"""
import re
from typing import Any, Dict, List, Optional

# Patrones de PII (ISO/IEC 27001 A.8.2 - identificación de datos sensibles)
PII_PATTERNS = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "phone_gt": re.compile(r'\b(?:\+?502)?\s?\d{4}[-.]?\d{4}\b'),
    "phone_intl": re.compile(r'\+\d{1,3}\s?\d{1,4}[-.]?\d{4,10}'),
    "credit_card": re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),
    "dpi_gt": re.compile(r'\b\d{4}\s?\d{5}\s?\d{4}\b'),  # CUI/DPI Guatemala
}

SANITIZATION_RULES = {
    "email": "[EMAIL_REDACTED]",
    "phone_gt": "[PHONE_REDACTED]",
    "phone_intl": "[PHONE_REDACTED]",
    "credit_card": "[CC_REDACTED]",
    "dpi_gt": "[DPI_REDACTED]",
}

def sanitize_pii(text: Optional[str]) -> Optional[str]:
    """
    Sanitiza información personal identificable (PII) en una cadena.
    Retorna la cadena con marcadores de redacción.
    """
    if not text or not isinstance(text, str):
        return text
    sanitized = text
    for pii_type, pattern in PII_PATTERNS.items():
        replacement = SANITIZATION_RULES.get(pii_type, "[REDACTED]")
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized

def sanitize_dict(data: Any, max_depth: int = 3) -> Any:
    """
    Sanitiza recursivamente diccionarios, listas y strings.
    Aplica sanitize_pii a todos los strings.
    """
    if max_depth <= 0:
        return data
    if isinstance(data, dict):
        return {k: sanitize_dict(v, max_depth - 1) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_dict(v, max_depth - 1) for v in data]
    if isinstance(data, str):
        return sanitize_pii(data)
    return data
