"""
market_intelligence.py - Implementa JTBD, ODI, VPC, Kano y priorización.
31JUL2026
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class MarketIntelligence:
    def extract_jobs(self, answers: List[Dict]) -> Dict[str, str]:
        jobs = {"functional": "", "emotional": "", "social": ""}
        functional_keywords = ["necesito", "requiero", "debo"]
        emotional_keywords = ["tranquilidad", "confianza", "seguridad", "preocupación"]
        social_keywords = ["negocio", "cliente", "familia", "comunidad"]
        for ans in answers:
            text = ans.get('answer_text', '').lower()
            if any(k in text for k in functional_keywords):
                jobs["functional"] = text
            if any(k in text for k in emotional_keywords):
                jobs["emotional"] = text
            if any(k in text for k in social_keywords):
                jobs["social"] = text
        return jobs

    def calculate_outcomes(self, answers: List[Dict]) -> List[Dict]:
        outcomes = []
        for ans in answers:
            text = ans.get('answer_text', '')
            match = re.search(r'(\d+)\s*kWh', text, re.IGNORECASE)
            if match:
                outcomes.append({
                    "metric": "Consumo energético",
                    "current": float(match.group(1)),
                    "desired": float(match.group(1)) * 0.7,
                    "importance": 1.0
                })
        return outcomes

    def build_vpc(self, answers: List[Dict]) -> Dict[str, List[str]]:
        vpc = {"pains": [], "gains": [], "jobs": []}
        for ans in answers:
            text = ans.get('answer_text', '').lower()
            if "pérdida" in text or "daño" in text or "problema" in text:
                vpc["pains"].append(text[:100])
            if "mejorar" in text or "ahorrar" in text or "beneficio" in text:
                vpc["gains"].append(text[:100])
            if "necesito" in text or "requiero" in text:
                vpc["jobs"].append(text[:100])
        return vpc

    def classify_features(self, features: List[str]) -> Dict[str, List[str]]:
        kano = {"basic": [], "performance": [], "differentiator": []}
        for feature in features:
            if any(k in feature.lower() for k in ["imprescindible", "necesario", "básico"]):
                kano["basic"].append(feature)
            elif any(k in feature.lower() for k in ["mejor", "más rápido", "eficiente"]):
                kano["performance"].append(feature)
            else:
                kano["differentiator"].append(feature)
        return kano

    def prioritize(self, specs: List[Dict]) -> List[Dict]:
        weights = {"impact": 0.35, "feasibility": 0.25, "profit": 0.20, "sustainability": 0.20}
        for spec in specs:
            impact = 0.8
            feasibility = 0.7
            profit = 0.6
            sustainability = 0.9
            score = (weights["impact"] * impact +
                     weights["feasibility"] * feasibility +
                     weights["profit"] * profit +
                     weights["sustainability"] * sustainability)
            spec["priority_score"] = round(score * 100, 2)
        return sorted(specs, key=lambda x: x.get("priority_score", 0), reverse=True)
