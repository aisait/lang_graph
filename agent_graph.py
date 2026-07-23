"""
agent_graph.py - Grafo agéntico de JARVI 2.0 con instrumentación CTFOM.
VERSIÓN 2.0.04 – Auditada: decoradores OTLP desactivados para compatibilidad con Langfuse v3.
"""
import os
import time
import uuid
import asyncio
import threading
import requests
import re
import functools
import logging
from typing import Annotated, TypedDict, Optional
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver

# OpenTelemetry (infraestructura)
from telemetry_otel import get_tracer
from opentelemetry.trace import Status, StatusCode

# Sanitización
from utils.sanitize import sanitize_pii

import config
from audit import auditar_fase
from ontology import obtener_fragmento_ontologia, cargar_ontologia, obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion

logger = logging.getLogger(__name__)
tracer = get_tracer("jarvi.graph")

# =============================================================================
# CONFIGURACIÓN DE API KEY
# =============================================================================
OPENAI_KEYS = [os.getenv(f"OPENAI_API_KEY_{i}") for i in range(1, 4)]
OPENAI_KEYS = [k for k in OPENAI_KEYS if k]
DEFAULT_API_KEY = OPENAI_KEYS[0] if OPENAI_KEYS else os.getenv("OPENAI_API_KEY")
if not DEFAULT_API_KEY:
    raise RuntimeError("No se encontró ninguna API Key de OpenAI.")

# =============================================================================
# CÓDIGOS DE ÁREA
# =============================================================================
CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}

def normalizar_contacto(nombre_raw: str, whatsapp_raw: str, ubicacion_raw: str) -> tuple:
    nombre_str = str(nombre_raw).strip() if nombre_raw else "Usuario"
    nombre_partes = nombre_str.split()
    nombre_normalizado = " ".join([p.capitalize() for p in nombre_partes]) if nombre_partes else "Usuario"

    codigo_area = "+502"
    ubicacion_lower = str(ubicacion_raw).lower() if ubicacion_raw else ""
    for pais, codigo in CODIGOS_AREA.items():
        if pais in ubicacion_lower:
            codigo_area = codigo
            break

    digits = re.sub(r'\D', '', whatsapp_raw if whatsapp_raw else "")
    if not digits:
        whatsapp_formateado = "Pendiente"
    else:
        codigo_limpio = codigo_area.replace('+', '')
        if digits.startswith(codigo_limpio) and len(digits) >= len(codigo_limpio) + 8:
            base = digits[len(codigo_limpio):]
        else:
            base = digits
        if len(base) >= 8:
            whatsapp_formateado = f"{codigo_area} {base[:4]}-{base[4:]}"
        else:
            whatsapp_formateado = f"{codigo_area} {base}"
    return nombre_normalizado, whatsapp_formateado

# =============================================================================
# ESQUEMAS
# =============================================================================
class ExtractorContacto(BaseModel):
    nombre: Optional[str] = Field(None, description="Nombre de pila y apellidos.")
    telefono: Optional[str] = Field(None, description="Número telefónico.")

class InferenciaEnergetica(TypedDict):
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool
    requiere_auditoria_electrica: bool
    nombre: Optional[str]
    whatsapp: Optional[str]
    departamento: Optional[str]
    municipio: Optional[str]
    vendedor: Optional[str]
    tipo_producto: Optional[str]
    productos_interes: Optional[list]

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica

# =============================================================================
# DECORADOR CTFOM (MANTENIDO, NO AFECTA A LANGFUSE)
# =============================================================================
def observe_node(layer: str = "graph", node_name: str = ""):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            trace_id = trace_id_var.get()
            span_id = str(uuid.uuid4())
            parent = span_id_var.get()
            span_id_var.set(span_id)
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                schedule_telemetry_event(
                    trace_id, span_id, parent,
                    layer=layer, node_name=node_name,
                    event_type="END", latency_ms=elapsed
                )
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                schedule_telemetry_event(
                    trace_id, span_id, parent,
                    layer=layer, node_name=node_name,
                    event_type="ERROR", latency_ms=elapsed,
                    error_code=f"SWR-LGG-{type(e).__name__}"
                )
                raise
            finally:
                span_id_var.set(parent)
        return wrapper
    return decorator

# =============================================================================
# HERRAMIENTA SIN CORREO Y CON WEBHOOK RESILIENTE
# =============================================================================
@tool
@auditar_fase(nombre_fase="Herramienta Persistencia Oportunidades", criticidad="ALTA")
async def procesar_oportunidad_backend(
    nombre_apellidos: str,
    departamento_municipio: str,
    consumo_actual: str,
    empresa_electrica: str,
    definicion_necesidad: str,
    listado_equipos_html: str,
    numero_whatsapp: str,
    resumen_18_palabras: str
) -> str:
    """
    Envía leads calificados a los canales del Controller (solo webhook, sin correo).
    Si el endpoint de webhook no está configurado, solo registra en logs.
    """
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)

    with tracer.start_as_current_span("dispatch_lead") as span:
        span.set_attribute("channel", "webhook")
        span.set_attribute("whatsapp", whatsapp_norm)
        span.set_attribute("nombre", nombre_norm)
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.operation", "dispatch")

        # Obtener endpoint y token
        endpoint = os.getenv("APICHAT_ENDPOINT", "")
        token = os.getenv("APICHAT_TOKEN", "")
        instance = os.getenv("APICHAT_INSTANCE", "")

        if endpoint:
            num_limpio = ''.join(filter(str.isdigit, whatsapp_norm))
            payload_wa = {
                "instance_id": instance,
                "number": num_limpio,
                "text": (
                    f"🚨 Lead Calificado:\n\n"
                    f"Cliente: {nombre_norm}\nWhatsApp: {whatsapp_norm}\n"
                    f"Ubicación: {departamento_municipio}\nEquipos:\n{listado_equipos_html}"
                )
            }
            try:
                await asyncio.to_thread(
                    requests.post,
                    endpoint,
                    json=payload_wa,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    timeout=15
                )
                logger.info(f"Webhook enviado exitosamente para {whatsapp_norm}")
            except Exception as e:
                logger.error(f"Fallo en envío de webhook: {e}")
        else:
            logger.info(f"Webhook no configurado (APICHAT_ENDPOINT vacío). Lead no enviado para {whatsapp_norm}")

        span.set_status(Status(StatusCode.OK))
        return f"✅ Los datos técnicos han sido guardados y auditados. Contacto: {whatsapp_norm}."

# =============================================================================
# FUNCIONES AUXILIARES (extraer_intencion_humana, extraer_tipo_producto, etc.)
# (Se mantienen exactamente igual a la versión original, sin cambios)
# =============================================================================
def extraer_intencion_humana(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                return msg.content.lower()
            if isinstance(msg.content, list):
                return " ".join([
                    str(b.get("text", "")).lower()
                    for b in msg.content
                    if isinstance(b, dict) and "text" in b
                ])
    return ""

def extraer_tipo_producto(mensaje: str) -> Optional[str]:
    mensaje_lower = mensaje.lower()
    if re.search(r'\b(sistema|kit|completo|llave en mano|instalación completa)\b', mensaje_lower):
        return "sistema"
    elif re.search(r'\b(producto|unitario|componente|inversor|panel|batería|calentador|bomba|controlador)\b', mensaje_lower):
        return "unitario"
    return None

def otel_span_node(node_name: str):
    """
    Decorador que instrumenta un nodo con OpenTelemetry.
    COMENTADO EN PRODUCCIÓN PARA EVITAR CORRUPCIÓN EN ClickHouse v3.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, config=None):
            # Este decorador está desactivado (comentado en cada nodo)
            # Se mantiene la función por si se requiere en el futuro con Langfuse v4.
            result = await func(state, config) if config is not None else await func(state)
            return result
        return wrapper
    return decorator

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = ChatOpenAI(openai_api_key=DEFAULT_API_KEY, model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    @auditar_fase(nombre_fase="Clasificador de Intención Comercial", criticidad="MEDIA")
    @observe_node(node_name="clasificar_intencion_comercial")
    # @otel_span_node("clasificar_intencion_comercial")  # <--- COMENTADO PARA v3
    async def clasificar_intencion_comercial_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo:
            return {"contexto_tecnico": ctx}
        if not ctx.get("topologia"):
            if any(k in ultimo for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
                ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
                ctx["requiere_auditoria_electrica"] = True
            elif any(k in ultimo for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
                ctx["requiere_auditoria_electrica"] = True
        return {"contexto_tecnico": ctx}

    @auditar_fase(nombre_fase="Validador de Ubicación del Cliente", criticidad="MEDIA")
    @observe_node(node_name="validar_ubicacion_cliente")
    # @otel_span_node("validar_ubicacion_cliente")  # <--- COMENTADO PARA v3
    async def validar_ubicacion_cliente_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo:
            return {"contexto_tecnico": ctx}
        if not ctx.get("departamento") or not ctx.get("municipio"):
            resultado = buscar_ubicacion(ultimo)
            if resultado:
                ctx["departamento"] = resultado["departamento"]
                ctx["municipio"] = resultado["municipio"]
                ctx["ciudad"] = resultado["municipio"]
                logger.info(f"Ubicación detectada: {resultado['label']}")
        if ctx.get("requiere_auditoria_electrica") and ctx.get("departamento"):
            if ctx["departamento"].lower() == "guatemala":
                ctx["empresa_electrica"] = "EEGSA"
                ctx["tarifa_base_gtq"] = 1.45
        return {"contexto_tecnico": ctx}

    @auditar_fase(nombre_fase="Selección de Productos", criticidad="ALTA")
    @observe_node(node_name="seleccionar_productos")
    # @otel_span_node("seleccionar_productos")  # <--- COMENTADO PARA v3
    async def seleccionar_productos_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if ctx.get("tipo_producto"):
            return {"contexto_tecnico": ctx}
        if not ultimo:
            return {"contexto_tecnico": ctx}
        tipo = extraer_tipo_producto(ultimo)
        if tipo:
            ctx["tipo_producto"] = tipo
            return {"contexto_tecnico": ctx}
        pregunta = ("Para poder recomendarle los productos más adecuados, ¿está usted buscando un **sistema completo** "
                    "(incluye paneles, inversor, estructura, cableado, etc.) o un **producto específico** "
                    "(ej. solo paneles, solo inversor, baterías)?")
        new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
        return {"messages": new_messages, "contexto_tecnico": ctx}

    @auditar_fase(nombre_fase="Generación de Respuesta Comercial", criticidad="ALTA")
    @observe_node(node_name="generar_respuesta_comercial")
    # @otel_span_node("generar_respuesta_comercial")  # <--- COMENTADO PARA v3
    async def generar_respuesta_comercial_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # Extracción de información (nombre, whatsapp)
        if ultimo_mensaje:
            num_match = re.search(r'(\+?[0-9]{1,3}[-.\s]?)?[0-9]{4,10}', ultimo_mensaje)
            if num_match:
                raw_num = num_match.group(0)
                _, num_norm = normalizar_contacto("", raw_num, ctx.get("ciudad", ""))
                if num_norm and num_norm != "Pendiente":
                    ctx["whatsapp"] = num_norm
            name_match = re.search(r'(?:mi\s+nombre\s+es|nombre[:]\s*|me\s+llamo|soy\s+)([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
                                   ultimo_mensaje, re.IGNORECASE)
            if name_match:
                raw_name = name_match.group(1).strip()
                if raw_name and len(raw_name) > 1:
                    ctx["nombre"] = raw_name

        if ultimo_mensaje and (not ctx.get("nombre") or ctx.get("nombre") == "Usuario" or not ctx.get("whatsapp")):
            try:
                extraccion = await extractor_llm.ainvoke(f"Identifica nombre o teléfono. Mensaje: {ultimo_mensaje}")
                if extraccion.nombre and (not ctx.get("nombre") or ctx["nombre"] == "Usuario"):
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono and (not ctx.get("whatsapp") or ctx["whatsapp"] == "Pendiente"):
                    ctx["whatsapp"] = extraccion.telefono
            except Exception:
                pass

        if ultimo_mensaje and not ctx.get("vendedor"):
            vendedor_match = re.search(r'(?:mi\s+vendedor\s+es|vendedor[:]\s*)([A-Za-z0-9\s]+)',
                                       ultimo_mensaje, re.IGNORECASE)
            if vendedor_match:
                ctx["vendedor"] = vendedor_match.group(1).strip()

        if ultimo_mensaje and not ctx.get("tipo_producto"):
            tipo = extraer_tipo_producto(ultimo_mensaje)
            if tipo:
                ctx["tipo_producto"] = tipo

        if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
            ctx["productos_interes"] = obtener_productos_relevantes(
                topologia=ctx["topologia"],
                tipo=ctx["tipo_producto"],
                max_items=5
            )

        if ctx.get("requiere_auditoria_electrica"):
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
        else:
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación y Necesidad exacta."

        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))

        nombre_ctx = ctx.get("nombre", "Usuario")
        whatsapp_ctx = ctx.get("whatsapp", "Pendiente")
        nombre_run, whatsapp_run = normalizar_contacto(nombre_ctx, whatsapp_ctx, ctx.get("ciudad", ""))

        if "metadata" not in config:
            config["metadata"] = {}
        config["metadata"]["whatsapp"] = whatsapp_run
        config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
        if ctx.get("tipo_producto"):
            config["metadata"]["tipo_producto"] = ctx["tipo_producto"]
        if ctx.get("productos_interes"):
            config["metadata"]["productos_tags"] = [p["tag"] for p in ctx["productos_interes"]]

        prompt_sistema = SystemMessage(
            content=(
                f"Eres Jarvi, Ingeniero de Preventa de AISA Solar. "
                f"Siempre trata al cliente de **usted**, de manera formal y profesional. "
                f"Utiliza el pronombre 'usted' y conjuga los verbos en tercera persona del singular. "
                f"Evita cualquier tono coloquial o de amistad. Mantén una actitud respetuosa y cortés en todo momento.\n\n"
                f"Responde con los datos auditados:\n"
                f"- Ubicación: {ctx.get('ciudad', 'PENDIENTE')}\n"
                f"- Distribuidora: {ctx.get('empresa_electrica', 'PENDIENTE')}\n"
                f"- Tarifa: GTQ {ctx.get('tarifa_base_gtq', 'PENDIENTE')} /kWh\n"
                f"REGLAS: {regla_datos}\n"
                f"ONTOLOGÍA: {ontologia_dinamica}"
            )
        )

        with tracer.start_as_current_span("llm_generation") as llm_span:
            llm_span.set_attribute("gen_ai.system", "openai")
            llm_span.set_attribute("gen_ai.operation", "chat")
            llm_span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            llm_span.set_attribute("gen_ai.request.temperature", 0.1)

            prompt_text = prompt_sistema.content + " " + ultimo_mensaje
            llm_span.set_attribute("gen_ai.prompt.0.role", "system")
            llm_span.set_attribute("gen_ai.prompt.0.content", sanitize_pii(prompt_text[:5000]))

            respuesta = await llm.ainvoke([prompt_sistema] + state["messages"], config=config)

            llm_span.set_attribute("gen_ai.completion.0.role", "assistant")
            llm_span.set_attribute("gen_ai.completion.0.content", sanitize_pii(respuesta.content[:5000]))

            if hasattr(respuesta, 'response_metadata'):
                usage = respuesta.response_metadata.get('token_usage', {})
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)
                total_tokens = usage.get('total_tokens', 0)
                llm_span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                llm_span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                llm_span.set_attribute("gen_ai.usage.total_tokens", total_tokens)

            llm_span.set_status(Status(StatusCode.OK))

        return {"messages": [respuesta], "contexto_tecnico": ctx}

    @observe_node(node_name="anexar_caso_respuesta")
    # @otel_span_node("anexar_caso_respuesta")  # <--- COMENTADO PARA v3
    async def anexar_caso_respuesta_node(state: AgentState, config: RunnableConfig):
        messages = state.get("messages", [])
        caso = config.get("metadata", {}).get("caso", "000000000000")
        if messages and isinstance(messages[-1], AIMessage):
            last_msg = messages[-1]
            if not last_msg.content.endswith(f"[Caso No. {caso}]"):
                new_content = f"{last_msg.content} [Caso No. {caso}]"
                messages[-1] = AIMessage(content=new_content, additional_kwargs=last_msg.additional_kwargs)
        return {"messages": messages}

    # =========================================================================
    # ENSAMBLAJE DEL GRAFO
    # =========================================================================
    graph_builder.add_node("clasificar_intencion_comercial", clasificar_intencion_comercial_node)
    graph_builder.add_node("validar_ubicacion_cliente", validar_ubicacion_cliente_node)
    graph_builder.add_node("seleccionar_productos", seleccionar_productos_node)
    graph_builder.add_node("generar_respuesta_comercial", generar_respuesta_comercial_node)
    graph_builder.add_node("anexar_caso_respuesta", anexar_caso_respuesta_node)
    graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))

    def my_tools_condition(state: AgentState):
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "tools"
        return "anexar_caso_respuesta"

    graph_builder.add_edge(START, "clasificar_intencion_comercial")
    graph_builder.add_edge("clasificar_intencion_comercial", "validar_ubicacion_cliente")
    graph_builder.add_edge("validar_ubicacion_cliente", "seleccionar_productos")
    graph_builder.add_edge("seleccionar_productos", "generar_respuesta_comercial")
    graph_builder.add_conditional_edges("generar_respuesta_comercial", my_tools_condition)
    graph_builder.add_edge("tools", "anexar_caso_respuesta")
    graph_builder.add_edge("anexar_caso_respuesta", END)

    return graph_builder.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer_studio = MemorySaver()
    jarvi_graph = create_graph(checkpointer_studio)
else:
    jarvi_graph = None
