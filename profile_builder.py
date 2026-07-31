"""
profile_builder.py - Genera el perfil final y especificaciones del producto.
31JUL2026
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ProfileBuilder:
    def build_summary(self, answers: List[Dict], states: Dict[str, Dict]) -> str:
        sections = []
        ident = states.get('IDENTIDAD', {})
        variables = ident.get('variables', {})
        sections.append(f"""
**IDENTIDAD DEL PROYECTO**
- Cliente: {variables.get('nombre', 'No especificado')}
- Actividad: {variables.get('actividad', 'No especificado')}
- Ubicación: {variables.get('ubicacion', 'No especificado')}
- Sector: {variables.get('sector', 'No especificado')}
""")
        prob = states.get('PROBLEMA', {})
        pvars = prob.get('variables', {})
        sections.append(f"""
**PROBLEMA Y NECESIDAD**
- Necesidad principal: {pvars.get('necesidad', 'No especificado')}
- Impacto actual: {pvars.get('impacto', 'No especificado')}
- Urgencia: {pvars.get('urgencia', 'No especificado')}
""")
        tec = states.get('TECNICA', {})
        tvars = tec.get('variables', {})
        sections.append(f"""
**CARACTERIZACIÓN TÉCNICA**
- Consumo mensual: {tvars.get('consumo_mensual_kwh', 'No especificado')} kWh
- Potencia pico: {tvars.get('potencia_pico', 'No especificado')} W
- Temperatura: {tvars.get('temperatura', 'No especificado')} °C
- Caudal: {tvars.get('caudal', 'No especificado')} L/h
""")
        comport = states.get('COMPORTAMIENTO', {})
        cvars = comport.get('variables', {})
        sections.append(f"""
**COMPORTAMIENTO Y NECESIDADES**
- Trabajo funcional: {cvars.get('jtbd_functional', 'No especificado')}
- Trabajo emocional: {cvars.get('jtbd_emotional', 'No especificado')}
- Dolores (Pains): {cvars.get('vpc_pains', 'No especificado')}
- Beneficios (Gains): {cvars.get('vpc_gains', 'No especificado')}
""")
        viab = states.get('VIABILIDAD', {})
        vvars = viab.get('variables', {})
        sections.append(f"""
**VIABILIDAD Y RESTRICCIONES**
- Recursos disponibles: {vvars.get('recursos', 'No especificado')}
- Condiciones especiales: {vvars.get('condiciones', 'No especificado')}
- Restricciones: {vvars.get('restricciones', 'No especificado')}
""")
        return "\n".join(sections)

    def generate_specs(self, answers: List[Dict], states: Dict[str, Dict]) -> List[Dict]:
        specs = []
        for ans in answers:
            text = ans.get('answer_text', '')
            if "consumo" in text.lower():
                match = re.search(r'(\d+)\s*kWh', text, re.IGNORECASE)
                if match:
                    specs.append({
                        "spec_name": "Consumo energético estimado",
                        "category": "technical",
                        "value": f"{match.group(1)} kWh/mes",
                        "priority_score": 85.0
                    })
        tvars = states.get('TECNICA', {}).get('variables', {})
        if tvars.get('potencia_pico'):
            specs.append({
                "spec_name": "Potencia pico requerida",
                "category": "technical",
                "value": f"{tvars['potencia_pico']} W",
                "priority_score": 90.0
            })
        return specs

    def generate_opportunity_matrix(self, vpc: Dict) -> str:
        lines = ["**MATRIZ DE OPORTUNIDADES (Design Thinking)**"]
        lines.append("- **Dolores identificados** (Pains):")
        for pain in vpc.get('pains', [])[:3]:
            lines.append(f"  - {pain}")
        lines.append("- **Beneficios esperados** (Gains):")
        for gain in vpc.get('gains', [])[:3]:
            lines.append(f"  - {gain}")
        lines.append("- **Tareas del cliente** (Jobs):")
        for job in vpc.get('jobs', [])[:3]:
            lines.append(f"  - {job}")
        return "\n".join(lines)
