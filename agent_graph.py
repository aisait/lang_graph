"""
agent_graph.py - Módulo central del grafo agéntico de JARVI 2.0.
Implementa un flujo de recolección de datos en 5 pasos.
"""

import os
import re
import json
import logging
import threading
import time
import uuid
import functools
from typing import Annotated, TypedDict, Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
import requests
from pydantic import BaseModel, Field

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.base import BaseCheckpointSaver

import config
from audit import auditar_fase
from ontology import obtener_fragmento_ontologia, buscar_productos_por_mensaje
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event
from db_client import actualizar_thread, registrar_evento_auditoria
from ubicacion import buscar_ubicacion

# =============================================================================
# CONFIGURACIÓN DE VENDEDORES
# =============================================================================
VENDEDORES_PATH = os.path.join(os.path.dirname(__file__), "vendedores.json")

def cargar_vendedores() -> List[Dict[str, Any]]:
    try:
        with open(VENDEDORES_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("vendedores", [])
    except:
        return [{"id": 1, "nombre": "Gerencia", "email": "gerencia@aisa.com.gt", "default": True}]

def buscar_vendedor_por_nombre(texto: str) -> Optional[Dict[str, Any]]:
    if not texto: return None
    texto = texto.lower().strip()
    for v in cargar_vendedores():
        if texto in v.get("nombre", "").lower():
            return v
    return None

def asignar_vendedor_default() -> str:
    for v in cargar_vendedores():
        if v.get("default", False):
            return v["email"]
    return "gerencia@aisa.com.gt"

def validar_campos_obligatorios(ctx: dict) -> bool:
    required = ["nombre", "whatsapp", "ubicacion", "productos", "vendedor"]
    return all(ctx.get(field) for field in required)

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
    whatsapp_str = str(whatsapp_raw) if whatsapp_raw else ""
    digits = re.sub(r'\D', '', whatsapp_str)
    if not digits:
        whatsapp_formateado = "Pendiente"
    else:
        codigo_limpio = codigo_area.replace('+', '')
        if digits.startswith(codigo_limpio) and len(digits) > len(codigo_limpio) + 5:
            base = digits[len(codigo_limpio):]
        else:
            base = digits
        if len(base) >= 8:
            whatsapp_formateado = f"{codigo_area} {base[:4]}-{base[4:]}"
        else:
            whatsapp_formateado = f"{codigo_area} {base}"
    return nombre_normalizado, whatsapp_formateado

# =============================================================================
# ESQUEMAS DE DATOS
# =============================================================================
class ExtractorContacto(BaseModel):
    nombre: Optional[str] = Field(None, description="Nombre completo")
    telefono: Optional[str] = Field(None, description="Número de teléfono")
    email: Optional[str] = Field(None, description="Correo electrónico")

class InferenciaEnergetica(TypedDict):
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool
    requiere_auditoria_electrica: bool
    nombre: Optional[str]
    whatsapp: Optional[str]
    email: Optional[str]
    productos: Optional[List[str]]
    vendedor: Optional[str]
    ubicacion: Optional[str]
    paso_actual: Optional[int]  # 0=inicio, 1=nombre, 2=whatsapp, 3=ubicacion, 4=productos, 5=vendedor, 6=completo

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica

# =============================================================================
# DECORADOR CTFOM
# =============================================================================
def observe_node(layer: str = "graph", node_name: str = ""):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            trace_id = trace_id_var.get()
            span_id = str(uuid.uuid4())
            parent = span_id_var.get()
            span_id_var.set(span_id)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                schedule_telemetry_event(trace_id, span_id, parent, layer=layer, node_name=node_name,
                                         event_type="END", latency_ms=elapsed)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                schedule_telemetry_event(trace_id, span_id, parent, layer=layer, node_name=node_name,
                                         event_type="ERROR", latency_ms=elapsed,
                                         error_code=f"SWR-LGG-{type(e).__name__}")
                raise
            finally:
                span_id_var.set(parent)
        return wrapper
    return decorator

# =============================================================================
# HERRAMIENTA DE PERSISTENCIA
# =============================================================================
@tool
@auditar_fase(nombre_fase="Herramienta Persistencia Oportunidades", criticidad="ALTA")
def procesar_oportunidad_backend(...):
    # (sin cambios, igual que en versiones anteriores)
    pass

def extraer_intencion_humana(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content.lower()
            elif isinstance(content, list):
                textos = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        textos.append(item["text"])
                    elif isinstance(item, str):
                        textos.append(item)
                return " ".join(textos).lower()
    return ""

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_retries=5).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # ---------- Nodo: Clasificador ----------
    @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
    @observe_node(node_name="clasificador_topologia")
    def clasificador_topologia_node(state: AgentState):
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

    # ---------- Nodo: Validador Geográfico ----------
    @auditar_fase(nombre_fase="Validador Geográfico", criticidad="MEDIA")
    @observe_node(node_name="validador_geolocalizacion")
    def validador_geolocalizacion_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo or ctx.get("ubicacion"):
            return {"contexto_tecnico": ctx}
        ubicacion = buscar_ubicacion(ultimo)
        if ubicacion:
            ctx["ubicacion"] = ubicacion["label"]
            ctx["ciudad"] = ubicacion["municipio"]
            if ctx.get("requiere_auditoria_electrica"):
                ctx["empresa_electrica"] = "EEGSA"
                ctx["tarifa_base_gtq"] = 1.45
        return {"contexto_tecnico": ctx}

    # ---------- Nodo: Chatbot (flujo de pasos) ----------
    @auditar_fase(nombre_fase="Inferencia del Chatbot", criticidad="ALTA")
    @observe_node(node_name="chatbot")
    def chatbot_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))
        logger = logging.getLogger("jarvi.agent")
        logger.info(f"[chatbot] contexto: {ctx}, paso: {ctx.get('paso_actual', 0)}")

        # --- Inicializar paso actual si no existe ---
        if "paso_actual" not in ctx:
            ctx["paso_actual"] = 0

        # --- PRIMERA INTERACCIÓN: bienvenida y empezar paso 1 ---
        if len(state.get("messages", [])) == 1:
            ctx["paso_actual"] = 1
            bienvenida = (
                "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar.\n\n"
                "Antes de ayudarte, necesito algunos datos:\n\n"
                "1️⃣ ¿Cómo te llamas?"
            )
            return {"messages": [AIMessage(content=bienvenida)], "contexto_tecnico": ctx}

        # --- EXTRACCIÓN DE DATOS DEL MENSAJE ---
        if ultimo_mensaje:
            try:
                extraccion = extractor_llm.invoke(
                    f"Del mensaje, extrae nombre (campo 'nombre'), teléfono (campo 'telefono') y email (campo 'email'). "
                    f"Mensaje: {ultimo_mensaje}"
                )
                if extraccion.nombre:
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono:
                    _, ctx["whatsapp"] = normalizar_contacto("", extraccion.telefono, "")
                if extraccion.email:
                    ctx["email"] = extraccion.email
            except Exception as e:
                logger.warning(f"Extractor LLM falló: {e}")

            # Intentar extraer ubicación si no está
            if not ctx.get("ubicacion"):
                ubicacion = buscar_ubicacion(ultimo_mensaje)
                if ubicacion:
                    ctx["ubicacion"] = ubicacion["label"]
                    ctx["ciudad"] = ubicacion["municipio"]

            # Productos
            if not ctx.get("productos") or len(ctx["productos"]) == 0:
                productos = buscar_productos_por_mensaje(ultimo_mensaje)
                if productos:
                    ctx["productos"] = productos

            # Vendedor
            if not ctx.get("vendedor"):
                vendedor = buscar_vendedor_por_nombre(ultimo_mensaje)
                if vendedor:
                    ctx["vendedor"] = vendedor["email"]

            # Topología
            if not ctx.get("topologia"):
                if any(k in ultimo_mensaje for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
                    ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
                    ctx["requiere_auditoria_electrica"] = True
                elif any(k in ultimo_mensaje for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                    ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
                    ctx["requiere_auditoria_electrica"] = True

            # --- Avanzar al siguiente paso según lo que ya tenemos ---
            if ctx.get("nombre") and ctx["paso_actual"] == 1:
                ctx["paso_actual"] = 2
            if ctx.get("whatsapp") and ctx["paso_actual"] == 2:
                ctx["paso_actual"] = 3
            if ctx.get("ubicacion") and ctx["paso_actual"] == 3:
                ctx["paso_actual"] = 4
            if ctx.get("productos") and len(ctx["productos"]) > 0 and ctx["paso_actual"] == 4:
                ctx["paso_actual"] = 5
            if ctx.get("vendedor") and ctx["paso_actual"] == 5:
                ctx["paso_actual"] = 6

        # --- PREGUNTAS SEGÚN EL PASO ACTUAL ---
        paso = ctx.get("paso_actual", 0)

        if paso == 1 and not ctx.get("nombre"):
            return {"messages": [AIMessage(content="¿Cómo te llamas?")], "contexto_tecnico": ctx}

        if paso == 2 and not ctx.get("whatsapp"):
            return {"messages": [AIMessage(content="¿Cuál es tu número de WhatsApp con código de país?")], "contexto_tecnico": ctx}

        if paso == 3 and not ctx.get("ubicacion"):
            return {"messages": [AIMessage(content="¿De qué municipio y departamento nos hablas?")], "contexto_tecnico": ctx}

        if paso == 4 and not ctx.get("productos"):
            return {"messages": [AIMessage(content="¿Qué productos o sistemas solares te interesan?")], "contexto_tecnico": ctx}

        if paso == 5 and not ctx.get("vendedor"):
            return {"messages": [AIMessage(content="¿Ya has recibido atención de algún vendedor de AISA Solar?")], "contexto_tecnico": ctx}

        # --- Si todos los campos están completos, persistir ---
        if validar_campos_obligatorios(ctx):
            if ctx.get("paso_actual") != 6:
                ctx["paso_actual"] = 6
                # Persistir en BD
                try:
                    import asyncio
                    thread_id = config.get("configurable", {}).get("thread_id")
                    if thread_id:
                        asyncio.run(actualizar_thread(
                            thread_id=thread_id,
                            nombre=ctx["nombre"],
                            whatsapp=ctx["whatsapp"],
                            email=ctx.get("email"),
                            productos=ctx["productos"],
                            vendedor=ctx["vendedor"],
                            trace_id=trace_id_var.get()
                        ))
                        asyncio.run(registrar_evento_auditoria(
                            thread_id=thread_id,
                            trace_id=trace_id_var.get(),
                            event_type="DATOS_CLIENTE_COMPLETOS",
                            source="chatbot_node",
                            payload=ctx
                        ))
                        logger.info(f"Datos persistidos: {ctx['nombre']} ({ctx['whatsapp']})")
                except Exception as e:
                    logger.error(f"Error al persistir: {e}")

        # --- ACTUALIZAR METADATOS Y run_name ---
        _, whatsapp_run = normalizar_contacto("", ctx.get("whatsapp", "Pendiente"), "")
        config["run_name"] = whatsapp_run
        config["metadata"] = config.get("metadata", {})
        config["metadata"]["whatsapp"] = whatsapp_run
        config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
        config["metadata"]["vendedor"] = ctx.get("vendedor", "gerencia@aisa.com.gt")
        config["metadata"]["tags"] = ctx.get("productos", [])
        config["metadata"]["ubicacion"] = ctx.get("ubicacion", "PENDIENTE")

        # --- SI EL FLUJO ESTÁ COMPLETO, RESPONDER PREGUNTAS TÉCNICAS ---
        if ctx.get("paso_actual") == 6:
            if ctx.get("requiere_auditoria_electrica"):
                regla_datos = "Recopila sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
            else:
                regla_datos = "Recopila sutilmente: Nombre, Ubicación y Necesidad exacta."

            ontologia_dinamica = obtener_fragmento_ontologia(ctx.get("topologia"))

            prompt_sistema = SystemMessage(
                content=(
                    f"Eres Jarvi, Ingeniero de Preventa de AISA Solar.\n"
                    f"Responde con los datos auditados:\n"
                    f"- Ubicación: {ctx.get('ubicacion', 'PENDIENTE')}\n"
                    f"- Distribuidora: {ctx.get('empresa_electrica', 'PENDIENTE')}\n"
                    f"- Tarifa: GTQ {ctx.get('tarifa_base_gtq', 'PENDIENTE')} /kWh\n"
                    f"REGLAS: {regla_datos}\n"
                    f"ONTOLOGÍA: {ontologia_dinamica}\n"
                    f"Cliente: {ctx.get('nombre', 'PENDIENTE')} | WhatsApp: {ctx.get('whatsapp', 'PENDIENTE')} | Email: {ctx.get('email', 'PENDIENTE')}\n"
                    f"Productos: {', '.join(ctx.get('productos', ['PENDIENTE']))}\n"
                    f"Vendedor: {ctx.get('vendedor', 'PENDIENTE')}"
                )
            )

            respuesta = llm.invoke([prompt_sistema] + state["messages"], config=config)
            if not respuesta.content:
                respuesta = AIMessage(content="Lo siento, no pude generar una respuesta. Intenta de nuevo.")
            return {"messages": [respuesta], "contexto_tecnico": ctx}

        # --- Si el flujo no está completo, no debería llegar aquí ---
        return {"messages": [AIMessage(content="Continuemos con los datos.")], "contexto_tecnico": ctx}

    # ---------- Ensamblaje ----------
    graph_builder.add_node("clasificador", clasificador_topologia_node)
    graph_builder.add_node("validador", validador_geolocalizacion_node)
    graph_builder.add_node("chatbot", chatbot_node)
    graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))
    graph_builder.add_edge(START, "clasificador")
    graph_builder.add_edge("clasificador", "validador")
    graph_builder.add_edge("validador", "chatbot")
    graph_builder.add_conditional_edges("chatbot", tools_condition)
    graph_builder.add_edge("tools", "chatbot")
    return graph_builder.compile(checkpointer=checkpointer)

# ---------- Exportación para Studio ----------
from langgraph.checkpoint.memory import MemorySaver
checkpointer_studio = MemorySaver()
jarvi_graph = create_graph(checkpointer_studio)
