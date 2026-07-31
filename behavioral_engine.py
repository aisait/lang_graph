"""
behavioral_engine.py - Disparadores para preguntas conductuales (BEI/CIT y JTBD).
31JUL2026
"""
import re
import logging
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

class BehavioralEngine:
    def __init__(self):
        self.incident_keywords = [
            "falla", "problema", "pérdida", "daño", "rotura", "apagón",
            "corte", "quemó", "avería", "susto", "frustración"
        ]
        self.jtbd_keywords = [
            "necesito", "quiero", "busco", "requiero", "esencial",
            "fundamental", "prioridad", "debo", "tengo que"
        ]
        self.emotion_keywords = [
            "ansiedad", "preocupación", "tranquilidad", "confianza",
            "seguridad", "incertidumbre", "angustia", "satisfacción"
        ]

    def detect_trigger(self, message: str, dimension: str) -> Tuple[bool, str, Dict]:
        msg_lower = message.lower()
        if any(k in msg_lower for k in self.incident_keywords) and dimension in ["PROBLEMA", "TECNICA"]:
            return (True, "bei_incident", {"narrative": message})
        if any(k in msg_lower for k in self.jtbd_keywords) and dimension in ["PROBLEMA", "COMPORTAMIENTO"]:
            return (True, "jtbd", {"functional": message})
        if any(k in msg_lower for k in self.emotion_keywords):
            return (True, "emotion", {"emotion": msg_lower})
        return (False, "", {})

    def get_bei_question(self) -> str:
        return "Cuénteme la última vez que tuvo una falla eléctrica que afectó su operación. ¿Qué ocurrió y cómo lo resolvió?"

    def get_jtbd_question(self) -> str:
        return "Si pudiera eliminar ese problema, ¿qué resultado concreto lograría?"

    def get_emotion_question(self) -> str:
        return "¿Cómo se sintió durante esa situación?"

    def get_vpc_question(self) -> str:
        return "Si pudiera eliminar ese problema por completo, ¿qué sería lo más valioso para usted?"
