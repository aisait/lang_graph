"""
epistemology.py - Orquestador del ciclo epistémico para el MICDP.
31JUL2026
"""
import json
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import openai

from project_repository import ProjectRepository
from behavioral_engine import BehavioralEngine
from semantic_coder import SemanticCoder
from market_intelligence import MarketIntelligence
from profile_builder import ProfileBuilder
from ontology import cargar_ontologia

logger = logging.getLogger(__name__)

DIMENSIONES = ["IDENTIDAD", "PROBLEMA", "TECNICA", "COMPORTAMIENTO", "VIABILIDAD", "SINTESIS"]
PESOS = {"IDENTIDAD": 0.05, "PROBLEMA": 0.10, "TECNICA": 0.25,
         "COMPORTAMIENTO": 0.25, "VIABILIDAD": 0.15, "SINTESIS": 0.20}
UMBRALES = {"IDENTIDAD": 0.85, "PROBLEMA": 0.80, "TECNICA": 0.90,
            "COMPORTAMIENTO": 0.85, "VIABILIDAD": 0.80, "SINTESIS": 0.95}

class EpistemologyOrchestrator:
    def __init__(self, repo: ProjectRepository, openai_client: openai.OpenAI):
        self.repo = repo
        self.client = openai_client
        self.behavioral = BehavioralEngine()
        self.coder = SemanticCoder()
        self.market = MarketIntelligence()
        self.profile = ProfileBuilder()
        self.dimensions = DIMENSIONES
        self.weights = PESOS
        self.thresholds = UMBRALES
        self.system_prompt = self._build_system_prompt()
        self.tools = self._build_tools()

    def _build_system_prompt(self) -> str:
        return """
Eres Jarvi, un agente conversacional para la definición de proyectos (MICDP).
Tu objetivo es guiar al usuario a través de una entrevista estructurada para construir
un perfil conceptual de su proyecto en energías renovables, refrigeración o afines.

Sigue estas pautas:
- Trata al cliente de "usted" de manera formal y profesional.
- Realiza preguntas de forma natural, adaptándote a las respuestas.
- Explora el comportamiento real (BEI/CIT) y los trabajos funcionales (JTBD).
- Valida la información con la ontología de AISA Solar (tools disponibles).
- Construye el perfil gradualmente, mostrando resúmenes en los hitos 25%, 50%, 75% y 90%.
- Si el cliente solicita pausa, derivación a humano o confirmación, actúa en consecuencia.
- No reveles que eres una IA; preséntate como representante de AISA Solar.
- No uses marcas externas; solo las que estén en la ontología.
- Mantén respuestas claras y evita jerga técnica innecesaria.
"""

    def _build_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "ontology_validator",
                    "description": "Verifica si un término (producto, keyword) existe en el catálogo de AISA Solar.",
                    "parameters": {
                        "type": "object",
                        "properties": {"mention": {"type": "string", "description": "Término a validar"}},
                        "required": ["mention"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "semantic_validator",
                    "description": "Valida una respuesta del usuario (rangos, tipos).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "variable": {"type": "string", "description": "Nombre de la variable"},
                            "value": {"type": "string", "description": "Valor proporcionado"}
                        },
                        "required": ["variable", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "supervisor_rules",
                    "description": "Evalúa una respuesta contra reglas de identidad, formato, fuentes y privacidad.",
                    "parameters": {
                        "type": "object",
                        "properties": {"response_text": {"type": "string", "description": "Texto a validar"}},
                        "required": ["response_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "record_incident",
                    "description": "Registra un incidente crítico (BEI/CIT) narrado por el usuario.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "narrative": {"type": "string"},
                            "impact_loss": {"type": "number"},
                            "duration_hours": {"type": "number"},
                            "emotion": {"type": "string"}
                        },
                        "required": ["narrative"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_jtbd",
                    "description": "Extrae trabajos funcionales, emocionales y sociales del mensaje.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "functional_job": {"type": "string"},
                            "emotional_job": {"type": "string"},
                            "social_job": {"type": "string"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_vpc",
                    "description": "Actualiza el Value Proposition Canvas.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pains": {"type": "array", "items": {"type": "string"}},
                            "gains": {"type": "array", "items": {"type": "string"}},
                            "jobs": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "classify_kano",
                    "description": "Clasifica una característica según el modelo Kano.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "feature": {"type": "string"},
                            "category": {"type": "string", "enum": ["basic", "performance", "differentiator"]}
                        },
                        "required": ["feature", "category"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_profile",
                    "description": "Genera el perfil final del proyecto (950-1250 palabras).",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "pause_session",
                    "description": "Pausa la sesión actual, guardando el estado.",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "handoff_human",
                    "description": "Deriva la conversación a un asesor humano.",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]

    async def process_message(self, thread_id: str, user_message: str) -> Dict[str, Any]:
        definition = await self.repo.get_definition(thread_id)
        if not definition:
            await self.repo.create_definition(thread_id)
            await self.repo.start_session(thread_id)
            return {"response": self._get_welcome(), "action": "question"}

        previous_id = definition.get('last_response_id')
        input_items = [{"role": "user", "content": user_message}]

        try:
            # =========================================================================
            # CORRECCIÓN: Usar openai.responses.create() en lugar de self.client.responses.create()
            # =========================================================================
            response = openai.responses.create(  # <-- CAMBIO AQUÍ
                model="gpt-4o-mini",
                instructions=self.system_prompt,
                input=input_items,
                tools=self.tools,
                store=True,
                previous_response_id=previous_id,
                reasoning={"effort": "medium"}
            )
        except Exception as e:
            logger.error(f"Error en Responses API: {e}")
            return {"response": "Lo siento, hubo un problema técnico. Intente de nuevo más tarde.", "action": "error"}

        await self.repo.update_definition(thread_id, {"last_response_id": response.id})

        output = response.output
        for item in output:
            if item.type == "function_call":
                await self._handle_tool_call(item, thread_id)

        assistant_message = next((o for o in output if o.type == "message"), None)
        content = assistant_message.content[0].text if assistant_message else ""

        completeness = await self._compute_overall_completeness(thread_id)

        if completeness >= 90.0:
            profile_text = await self._generate_final_profile(thread_id)
            await self.repo.update_profile(thread_id, final_text=profile_text)
            return {"response": profile_text, "action": "completed", "completeness": completeness}
        elif completeness >= 25.0 and completeness < 30.0:
            summary = await self._generate_summary(thread_id, "early")
            content = f"{content}\n\n{summary}"
        elif completeness >= 50.0 and completeness < 55.0:
            summary = await self._generate_summary(thread_id, "intermediate")
            content = f"{content}\n\n{summary}"
        elif completeness >= 75.0 and completeness < 80.0:
            summary = await self._generate_summary(thread_id, "advanced")
            content = f"{content}\n\n{summary}"

        return {"response": content, "action": "question", "completeness": completeness}

    async def _handle_tool_call(self, tool_call, thread_id):
        name = tool_call.name
        args = tool_call.arguments
        if name == "ontology_validator":
            return self._ontology_validator(args.get("mention"))
        elif name == "semantic_validator":
            return self._semantic_validator(args.get("variable"), args.get("value"))
        elif name == "supervisor_rules":
            return self._supervisor_rules(args.get("response_text"))
        elif name == "record_incident":
            await self.repo.add_incident(
                thread_id=thread_id,
                narrative=args.get("narrative"),
                impact_loss_gtq=args.get("impact_loss"),
                duration_hours=args.get("duration_hours"),
                emotion_tag=args.get("emotion")
            )
        elif name == "extract_jtbd":
            await self.repo.add_job(
                thread_id=thread_id,
                functional_job=args.get("functional_job"),
                emotional_job=args.get("emotional_job"),
                social_job=args.get("social_job")
            )
        elif name == "update_vpc":
            await self.repo.update_vpc(
                thread_id=thread_id,
                pains=args.get("pains"),
                gains=args.get("gains"),
                jobs=args.get("jobs")
            )
        elif name == "classify_kano":
            await self.repo.add_kano_feature(
                thread_id=thread_id,
                feature_name=args.get("feature"),
                category=args.get("category")
            )
        elif name == "generate_profile":
            profile_text = await self._generate_final_profile(thread_id)
            await self.repo.update_profile(thread_id, final_text=profile_text)
            return {"profile": profile_text}
        elif name == "pause_session":
            await self.repo.update_definition(thread_id, {"is_active": False})
        elif name == "handoff_human":
            await self.repo.update_definition(thread_id, {"is_active": False})

    def _ontology_validator(self, mention):
        ontologia = cargar_ontologia()
        for tag, item in ontologia.items():
            if mention.lower() in item.get("nombre", "").lower() or any(kw.lower() == mention.lower() for kw in item.get("keywords", [])):
                return {"valid": True, "tag": tag, "nombre": item.get("nombre")}
        return {"valid": False, "message": "No se encontró en el catálogo."}

    def _semantic_validator(self, variable, value):
        try:
            if variable in ["consumo_mensual_kwh", "potencia_pico"]:
                val = float(value)
                if val < 0:
                    return {"valid": False, "message": "El valor debe ser positivo."}
                return {"valid": True, "value": val}
        except:
            return {"valid": False, "message": "Formato inválido."}
        return {"valid": True, "value": value}

    def _supervisor_rules(self, response_text):
        from supervisor_jarvi import SupervisorJarvi
        sup = SupervisorJarvi("rules.json")
        result = sup.evaluate({"response": response_text, "output_type": "response"})
        return {"passed": result["decision"] == "allow", "violation": result.get("rule_id")}

    async def _compute_overall_completeness(self, thread_id: str) -> float:
        total = 0.0
        for dim in self.dimensions:
            state = await self.repo.get_state(thread_id, dim)
            comp = state.get('completeness', 0.0) if state else 0.0
            total += self.weights[dim] * min(comp / self.thresholds[dim], 1.0)
        return round(total * 100, 2)

    async def _generate_summary(self, thread_id: str, stage: str) -> str:
        completeness = await self._compute_overall_completeness(thread_id)
        return f"""
📋 **BORRADOR DE PERFIL - PROYECTO {thread_id[:8]}**
(Completitud: {completeness:.0f}%)

📊 **VARIABLES PENDIENTES:**
- Revise las preguntas que aún no ha respondido.

🔄 ¿Desea corregir, complementar o confirmar la información?
Responda "Corregir [dato]", "Complementar" o "Confirmar".
"""

    async def _generate_final_profile(self, thread_id: str) -> str:
        # Aquí se llamaría a profile_builder con los datos de la BD
        return """
📘 **PERFIL CONCEPTUAL PERSONALIZADO DE PROYECTO**

**Resumen Ejecutivo**
- Cliente: ...
- Necesidad principal: ...
- Ubicación: ...

**Caracterización del Problema**
- Impacto actual: ...
- Urgencia: ...

**Variables Técnicas**
- Consumo: ...
- Potencia: ...
- Tipo de sistema: ...

**Dimensionamiento Conceptual**
- Estimación de componentes: ...

**Recomendaciones Técnicas**
- Basadas en literatura científica: ...

**Nivel de Confianza**
- Identidad: 95%
- Problema: 90%
- Técnica: 85%
- Comportamiento: 92%
- Viabilidad: 88%
- Síntesis: 95%

Gracias por participar en esta investigación. Este perfil es orientativo.
"""

    def _get_welcome(self) -> str:
        return """
Bienvenido(a) al Proceso Conversacional para la Definición de Proyectos.

Este espacio forma parte de una investigación académica orientada al desarrollo de un modelo inteligente para identificar necesidades y apoyar la formulación conceptual de proyectos relacionados con:

✅ Energías renovables.
✅ Sistemas fotovoltaicos.
✅ Refrigeración industrial y doméstica.
✅ Cadena de frío.
✅ Bombeo de agua.
✅ Eficiencia energética.
✅ Procesos industriales.
✅ Soluciones tecnológicas para hogares, comercios e industrias.

Su participación es voluntaria y tiene fines exclusivamente académicos, científicos y de investigación de necesidades.

Durante la conversación, le realizaré preguntas de forma natural para comprender su contexto, sus necesidades, sus objetivos y las condiciones técnicas de su proyecto. No existe un cuestionario fijo; la conversación se adapta a la información que usted proporciona.

Puede pausar y retomar la entrevista en cualquier momento. El sistema recordará el estado de su proyecto y continuará desde donde quedó.

¿Listo para comenzar? Solo responda "Sí" o "Adelante" cuando esté preparado.
"""
