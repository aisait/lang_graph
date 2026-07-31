"""
semantic_coder.py - Extracción de temas emergentes (Grounded Theory).
31JUL2026
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SemanticCoder:
    def __init__(self):
        pass

    def open_coding(self, text: str) -> List[str]:
        """Codificación abierta: extrae temas básicos."""
        temas = []
        # Heurística simple: buscar patrones de palabras clave
        patrones = [
            r'\b(consumo|energía|potencia|kWh|vatios)\b',
            r'\b(costo|precio|ahorro|inversión)\b',
            r'\b(falla|pérdida|daño|emergencia)\b'
        ]
        for patron in patrones:
            if re.search(patron, text, re.IGNORECASE):
                temas.append(patron)
        return temas

    def axial_coding(self, codes: List[str]) -> List[Dict[str, Any]]:
        """Codificación axial: relaciona códigos."""
        return [{"code": c, "category": "technical" if "kWh" in c else "economic"} for c in codes]

    def selective_coding(self, categories: List[Dict]) -> str:
        """Codificación selectiva: identifica tema central."""
        if not categories:
            return "sin categoría"
        # Simulación: elegir la categoría más frecuente
        return categories[0].get("category", "unknown")
