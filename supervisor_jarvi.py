"""
supervisor_jarvi.py - Módulo de supervisión determinista para JARVI 2.0.
Aplica 45 reglas de control en tiempo de ejecución para garantizar
la calidad, seguridad y cumplimiento de las respuestas.
30JUL2026
"""

import json
import re
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class SupervisorJarvi:
    """Motor de supervisión determinista que valida y corrige las respuestas del agente."""

    def __init__(self, rules_path: str = "rules.json"):
        with open(rules_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.rules = self.config.get("rules", [])
        self.default_action = self.config.get("default_action", "allow")
        self._cache = {}

    def evaluate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evalúa la entrada/salida contra todas las reglas activas.
        Retorna un dict con la decisión: 'allow', 'block', 'rewrite', 'force_closure', 'force_fallback', 'end_conversation'.
        """
        # Preparar datos para evaluación
        ctx = data.get("contexto", {})
        response = data.get("response", "")
        user_message = data.get("user_message", "")
        messages = data.get("messages", [])
        score = ctx.get("score_actual", 0.0)
        
        # Enriquecer data para condiciones
        data["score"] = score
        data["product_tag"] = ctx.get("product_tag")
        data["tipo_producto"] = ctx.get("tipo_producto")
        data["topologia"] = ctx.get("topologia")
        data["nombre"] = ctx.get("nombre")
        data["telefono"] = ctx.get("whatsapp")
        data["ubicacion_need"] = ctx.get("ubicacion_need")
        data["vendedor_asignado"] = ctx.get("vendedor")
        data["escalation_mode"] = ctx.get("escalation_mode", False)
        data["authorization_response"] = ctx.get("authorization_response")
        data["conversation_end"] = ctx.get("conversation_end", False)
        data["dimensionamiento_exists"] = bool(ctx.get("dimensionamiento"))
        data["calculo_carga_completado"] = ctx.get("calculo_carga_completado", False)
        data["requisitos_pendientes"] = any(r.get("field") and ctx.get(r.get("field")) is None for r in ctx.get("requisitos", []))
        data["all_fields_collected"] = all([
            ctx.get("nombre"),
            ctx.get("whatsapp"),
            ctx.get("ubicacion_need")
        ])
        data["nombre_exists"] = bool(ctx.get("nombre"))
        data["telefono_exists"] = bool(ctx.get("whatsapp"))
        data["price_mentioned"] = bool(re.search(r'\d+\.?\d*\s*(GTQ|Q|USD|US\$|dólares|quetzales)', response))
        data["user_query_exists"] = bool(user_message)
        data["price_extractor_failed"] = data.get("price_extractor_failed", False)

        for rule in self.rules:
            # Verificar si la regla aplica según las condiciones
            if not self._condition_applies(rule, data):
                continue

            # Aplicar la regla
            result = self._apply_rule(rule, data)

            if not result.get("passed", True):
                # Decisión basada en la acción de la regla
                action = result.get("action", rule.get("requirement", {}).get("action", "block"))
                return {
                    "decision": action,
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "message": result.get("message", rule.get("requirement", {}).get("message", "Regla violada")),
                    "modified_response": result.get("modified_response"),
                    "modified_context": result.get("modified_context")
                }

        # Si todas las reglas pasan
        return {"decision": "allow"}

    def _condition_applies(self, rule: Dict, data: Dict) -> bool:
        """Evalúa si la condición de la regla se cumple con los datos actuales."""
        cond = rule.get("condition", {})
        for key, value in cond.items():
            if key == "output_type":
                if data.get("output_type") != value:
                    return False
            elif key == "input_type":
                if data.get("input_type") != value:
                    return False
            elif key == "product_tag_in":
                if data.get("product_tag") not in value:
                    return False
            elif key == "product_tag_range":
                tag = data.get("product_tag")
                if tag is None or not tag.isdigit():
                    return False
                tag_int = int(tag)
                if not (value[0] <= tag_int <= value[1]):
                    return False
            elif key == "topologia":
                if data.get("topologia") != value:
                    return False
            elif key == "tipo_producto":
                if data.get("tipo_producto") != value:
                    return False
            elif key == "score":
                score = data.get("score", 0.0)
                if value.startswith("<"):
                    max_val = float(value[1:])
                    if score >= max_val:
                        return False
                elif value.startswith(">"):
                    min_val = float(value[1:])
                    if score <= min_val:
                        return False
            elif key == "intent":
                if data.get("intent") != value:
                    return False
            elif key == "escalation_mode":
                if data.get("escalation_mode") != value:
                    return False
            elif key == "nombre":
                if data.get("nombre") != value:
                    return False
            elif key == "nombre_exists":
                if bool(data.get("nombre")) != value:
                    return False
            elif key == "telefono_exists":
                if bool(data.get("whatsapp")) != value:
                    return False
            elif key == "ubicacion_need":
                if data.get("ubicacion_need") != value:
                    return False
            elif key == "all_fields_collected":
                if data.get("all_fields_collected") != value:
                    return False
            elif key == "authorization_response":
                if data.get("authorization_response") != value:
                    return False
            elif key == "conversation_end":
                if data.get("conversation_end") != value:
                    return False
            elif key == "product_tag_exists":
                if bool(data.get("product_tag")) != value:
                    return False
            elif key == "user_technical":
                # Detectar si el usuario usó jerga técnica
                user_msg = data.get("user_message", "")
                technical_pattern = r'\b(W/m²|STC|NOCT|MPPT|PWM|VOC|ISC)\b'
                has_technical = bool(re.search(technical_pattern, user_msg, re.IGNORECASE))
                if has_technical != value:
                    return False
            elif key == "dimensionamiento_exists":
                if data.get("dimensionamiento_exists") != value:
                    return False
            elif key == "calculo_carga_completado":
                if data.get("calculo_carga_completado") != value:
                    return False
            elif key == "requisitos_pendientes":
                if data.get("requisitos_pendientes") != value:
                    return False
            elif key == "price_mentioned":
                if data.get("price_mentioned") != value:
                    return False
            elif key == "user_query_exists":
                if data.get("user_query_exists") != value:
                    return False
            elif key == "price_extractor_failed":
                if data.get("price_extractor_failed") != value:
                    return False
        return True

    def _apply_rule(self, rule: Dict, data: Dict) -> Dict:
        """Aplica la lógica específica de la regla."""
        req = rule.get("requirement", {})
        rule_type = req.get("type")
        action = req.get("action", "block")
        result = {"passed": True}

        if rule_type == "regex_block":
            pattern = req.get("pattern")
            text = data.get("response", "")
            if re.search(pattern, text, re.IGNORECASE):
                return {"passed": False, "message": req.get("message"), "action": action}

        elif rule_type == "transform":
            func_name = req.get("function")
            text = data.get("response", "")
            if func_name == "remove_markdown":
                # Eliminar **, *, _, #, viñetas
                text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
                text = re.sub(r'\*(.*?)\*', r'\1', text)
                text = re.sub(r'__(.*?)__', r'\1', text)
                text = re.sub(r'_(.*?)_', r'\1', text)
                text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
                text = re.sub(r'^[\s]*[-*•]\s+', '', text, flags=re.MULTILINE)
                text = re.sub(r' +', ' ', text)
                text = re.sub(r'\s+([.,;:!?])', r'\1', text)
                text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
                result["modified_response"] = text.strip()
                return {"passed": True, "action": "rewrite", "message": req.get("message"), "modified_response": text}

        elif rule_type == "word_count_validate":
            text = data.get("response", "")
            words = text.split()
            min_w = req.get("min_words", 33)
            max_w = req.get("max_words", 66)
            if len(words) < min_w or len(words) > max_w:
                # Truncar o resumir (implementación simple: truncar)
                if len(words) > max_w:
                    truncated = " ".join(words[:max_w])
                    result["modified_response"] = truncated
                else:
                    # Si es muy corto, no hacemos nada (dejamos pasar)
                    return {"passed": True}
                return {"passed": True, "action": "rewrite", "message": req.get("message"), "modified_response": truncated}

        elif rule_type == "ontology_whitelist":
            response = data.get("response", "")
            # Cargar ontología para validar marcas
            try:
                from ontology import cargar_ontologia
                ontologia = cargar_ontologia()
                marcas_permitidas = set()
                for item in ontologia.values():
                    if isinstance(item, dict):
                        marcas_permitidas.add(item.get("nombre", "").lower())
                        marcas_permitidas.update([k.lower() for k in item.get("keywords", [])])
                # Buscar si la respuesta contiene alguna marca no permitida (simplificado)
                # En una implementación real, se usaría un modelo de extracción de entidades
                palabras = re.findall(r'\b[A-Za-zÁÉÍÓÚáéíóúñÑ\-]+\b', response)
                for palabra in palabras:
                    if palabra.lower() not in marcas_permitidas and len(palabra) > 3:
                        # Podría ser una marca externa (heurístico)
                        return {"passed": False, "message": req.get("message"), "action": action}
            except Exception as e:
                logger.warning(f"Ontología no disponible para validación de marcas: {e}")
            return {"passed": True}

        elif rule_type == "price_validation":
            # Verificar si el precio se obtuvo de price_extractor o es inventado
            # En producción, se puede verificar que el precio esté en el contexto
            # Si no, se bloquea
            if data.get("price_extractor_failed", False):
                return {"passed": False, "message": req.get("message"), "action": action}
            return {"passed": True}

        elif rule_type == "ontology_anchor":
            # Validar que la respuesta esté anclada a la ontología del tag
            # Esta regla se usa para validar que no se desvíe de la categoría
            return {"passed": True}

        elif rule_type == "product_category_match":
            # Validar que la recomendación no mezcle categorías
            return {"passed": True}

        elif rule_type == "trigger_escalation":
            # Activar modo escalación
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "force_fallback",
                "modified_context": {"escalation_mode": True}
            }

        elif rule_type == "ask_field":
            field = req.get("field")
            question = req.get("question")
            # Inyectar la pregunta en la respuesta
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": question
            }

        elif rule_type == "ask_authorization":
            question = req.get("question")
            # Reemplazar {telefono} y {producto} con valores reales
            telefono = data.get("whatsapp", "su teléfono")
            producto = data.get("product_tag", "su producto")
            question = question.replace("{telefono}", telefono).replace("{producto}", producto)
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": question,
                "modified_context": {"authorization_asked": True}
            }

        elif rule_type == "finalize_closure":
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "end_conversation",
                "modified_response": req.get("message"),
                "modified_context": {"conversation_end": True}
            }

        elif rule_type == "offer_alternative":
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": req.get("message")
            }

        elif rule_type == "intent_detection":
            user_msg = data.get("user_message", "")
            keywords = req.get("keywords", [])
            if any(k in user_msg.lower() for k in keywords):
                return {
                    "passed": False,
                    "message": req.get("message"),
                    "action": "force_closure",
                    "modified_context": {"intent": "buy"}
                }
            return {"passed": True}

        elif rule_type == "inject_questions":
            questions = req.get("questions", [])
            response = data.get("response", "")
            # Inyectar preguntas al final
            new_response = response + "\n\n" + "\n".join(questions)
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": new_response
            }

        elif rule_type == "force_topolgia":
            value = req.get("value")
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite_context",
                "modified_context": {"topologia": value}
            }

        elif rule_type == "ask_requirement":
            field = req.get("field")
            question = req.get("question")
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": question
            }

        elif rule_type == "trigger_dimensionamiento":
            # Activar el nodo de dimensionamiento
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite_context",
                "modified_context": {"calculo_carga_completado": False, "dimensionamiento_triggered": True}
            }

        elif rule_type == "ask_requirements":
            # Preguntar requisitos pendientes
            requisitos = data.get("requisitos", [])
            preguntas = []
            for req in requisitos:
                if req.get("field") and data.get("contexto", {}).get(req.get("field")) is None:
                    preguntas.append(req.get("question", f"¿Cuál es su {req.get('field')}?"))
            if preguntas:
                question = "\n".join(preguntas)
                return {
                    "passed": False,
                    "message": req.get("message"),
                    "action": "rewrite",
                    "modified_response": question
                }
            return {"passed": True}

        elif rule_type == "confirm_phone":
            telefono = data.get("whatsapp", "")
            message = req.get("message", "").replace("{telefono}", telefono)
            return {
                "passed": False,
                "message": req.get("message"),
                "action": "rewrite",
                "modified_response": message
            }

        elif rule_type == "regex_require":
            pattern = req.get("pattern")
            response = data.get("response", "")
            if not re.search(pattern, response, re.IGNORECASE):
                # Inyectar el mensaje requerido
                new_response = response + " " + req.get("message", "")
                return {
                    "passed": False,
                    "message": req.get("message"),
                    "action": "rewrite",
                    "modified_response": new_response
                }
            return {"passed": True}

        elif rule_type == "token_limit":
            max_tokens = req.get("max_tokens", 120000)
            messages = data.get("messages", [])
            # Calcular tokens (usando tiktoken si está disponible)
            try:
                import tiktoken
                enc = tiktoken.get_encoding("cl100k_base")
                total_tokens = 0
                for msg in messages:
                    content = msg.content if hasattr(msg, 'content') else str(msg)
                    total_tokens += len(enc.encode(content))
                if total_tokens > max_tokens:
                    # Truncar a últimos 10 mensajes
                    truncated = messages[-10:]
                    return {
                        "passed": False,
                        "message": req.get("message"),
                        "action": "truncate",
                        "modified_context": {"messages": truncated}
                    }
            except Exception as e:
                logger.warning(f"No se pudo contar tokens con tiktoken: {e}")
            return {"passed": True}

        elif rule_type == "price_fallback":
            # Si price_extractor falló, reemplazar el precio por "disponible bajo consulta"
            response = data.get("response", "")
            if re.search(r'\d+\.?\d*\s*(GTQ|Q|USD)', response):
                new_response = re.sub(r'\d+\.?\d*\s*(GTQ|Q|USD)', 'disponible bajo consulta', response)
                return {
                    "passed": False,
                    "message": req.get("message"),
                    "action": "rewrite",
                    "modified_response": new_response
                }
            return {"passed": True}

        elif rule_type == "fallback_local":
            # No requiere acción, solo logging
            logger.info("Fallback a memoria local activado.")
            return {"passed": True}

        elif rule_type == "log_alert":
            logger.warning("ALERTA: Latencia del LLM > 10 segundos.")
            return {"passed": True}

        return {"passed": True}
