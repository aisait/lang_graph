"""
agent_graph.py
Módulo central del grafo agéntico de JARVI 2.0.
Contiene la definición del estado compartido, herramientas, nodos de razonamiento
y la función de construcción del grafo con persistencia en PostgreSQL.
Incorpora el decorador CTFOM de telemetría cognitiva para la observabilidad
de cada nodo del grafo (trazas, latencia, errores).

Estándares: ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
Pruebas de caja negra: BC‑T01 a BC‑T10 (ver anexo).
"""

import os
import time
import uuid
import threading
import requests
import re
import functools
import json
import logging
from typing import Annotated, TypedDict, Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from pydantic import BaseModel, Field

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
from ontology import obtener_fragmento_ontologia, buscar_productos_por_mensaje  # <-- NUEVA IMPORTACIÓN
# --- CTFOM: módulo de telemetría cognitiva ---
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event

# === NUEVO: Importación del cliente de base de datos ===
from db_client import actualizar_thread, obtener_thread_por_whatsapp, registrar_evento_auditoria

# =============================================================================
# === NUEVO: CONFIGURACIÓN DE VENDEDORES ===
# =============================================================================
VENDEDORES_PATH = os.path.join(os.path.dirname(__file__), "vendedores.json")

def cargar_vendedores() -> List[Dict[str, Any]]:
    """Carga la lista de vendedores desde el archivo JSON."""
    try:
        with open(VENDEDORES_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("vendedores", [])
    except Exception as e:
        logging.getLogger("jarvi.agent").warning(f"Error al cargar vendedores: {e}")
        return [{"id": 1, "nombre": "Gerencia", "email": "gerencia@aisa.com.gt", "default": True}]

def asignar_vendedor(whatsapp: str = None) -> str:
    """Asigna un vendedor basado en el WhatsApp (si se proporciona) o retorna el default (gerencia)."""
    vendedores = cargar_vendedores()
    for v in vendedores:
        if v.get("default", False):
            return v["email"]
    return "gerencia@aisa.com.gt"

def validar_campos_obligatorios(ctx: dict) -> bool:
    """Verifica que todos los campos obligatorios estén presentes en el contexto."""
    required = ["nombre", "whatsapp", "email", "productos", "vendedor"]
    return all(ctx.get(field) for field in required)

# =============================================================================
# FIN DE LAS NUEVAS FUNCIONES
# =============================================================================

# ---------------------------------------------------------------------------
# Diccionario de códigos de área para Centroamérica
# ---------------------------------------------------------------------------
CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}


def normalizar_contacto(nombre_raw: str, whatsapp_raw: str, ubicacion_raw: str) -> tuple:
    # ... (código original, sin cambios) ...
    pass  # (omitido por brevedad, se mantiene exactamente igual)


# ---------------------------------------------------------------------------
# Esquemas de datos
# ---------------------------------------------------------------------------
class ExtractorContacto(BaseModel):
    nombre: Optional[str] = Field(None, description="Nombre de pila y apellidos.")
    telefono: Optional[str] = Field(None, description="Número telefónico.")
    email: Optional[str] = Field(None, description="Correo electrónico.")  # NUEVO


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
    preguntando_whatsapp: Optional[bool]
    preguntando_email: Optional[bool]
    preguntando_productos: Optional[bool]


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica


# ---------------------------------------------------------------------------
# Decorador CTFOM
# ---------------------------------------------------------------------------
def observe_node(layer: str = "graph", node_name: str = ""):
    # ... (sin cambios) ...
    pass


# ---------------------------------------------------------------------------
# Herramienta de persistencia de oportunidades
# ---------------------------------------------------------------------------
@tool
@auditar_fase(nombre_fase="Herramienta Persistencia Oportunidades", criticidad="ALTA")
def procesar_oportunidad_backend(...):
    # ... (sin cambios) ...
    pass


def extraer_intencion_humana(messages: list) -> str:
    # ... (sin cambios) ...
    pass


# ---------------------------------------------------------------------------
# Construcción del grafo
# ---------------------------------------------------------------------------
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # -------------------- Nodo: Clasificador Topológico --------------------
    @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
    @observe_node(node_name="clasificador_topologia")
    def clasificador_topologia_node(state: AgentState):
        # ... (sin cambios) ...
        pass

    # -------------------- Nodo: Validador Geográfico --------------------
    @auditar_fase(nombre_fase="Validador Geográfico", criticidad="MEDIA")
    @observe_node(node_name="validador_geolocalizacion")
    def validador_geolocalizacion_node(state: AgentState):
        # ... (sin cambios) ...
        pass

    # -------------------- Nodo: Chatbot --------------------
    @auditar_fase(nombre_fase="Inferencia del Chatbot", criticidad="ALTA")
    @observe_node(node_name="chatbot")
    def chatbot_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))
        logger = logging.getLogger("jarvi.agent")
        logger.info(f"[chatbot] contexto_tecnico recibido = {ctx}")

        # --- PRIMERA INTERACCIÓN ---
        if len(state.get("messages", [])) == 1:
            bienvenida = (
                "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar.\n"
                "Antes de comenzar, necesito algunos datos para poder ayudarte mejor:\n\n"
                "1️⃣ Tu nombre completo\n"
                "2️⃣ Tu número de WhatsApp (con código de país, ej. +502 1234-5678)\n"
                "3️⃣ Tu correo electrónico (para enviarte la cotización)\n"
                "4️⃣ ¿Qué productos te interesan? (ej. paneles solares, calentadores, bombas)\n\n"
                "¡Empecemos! ¿Cómo te llamas?"
            )
            return {"messages": [AIMessage(content=bienvenida)], "contexto_tecnico": ctx}

        # --- RECOLECCIÓN DE DATOS ---
        if ultimo_mensaje:
            try:
                extraccion = extractor_llm.invoke(
                    f"Extrae nombre, teléfono y email de este mensaje: {ultimo_mensaje}. "
                    "Devuelve solo JSON con los campos nombre, telefono, email."
                )
                if extraccion.nombre:
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono:
                    _, ctx["whatsapp"] = normalizar_contacto("", extraccion.telefono, "")
                if extraccion.email:
                    ctx["email"] = extraccion.email
            except Exception as e:
                logger.warning(f"Fallo en extracción LLM: {e}")

            # Ciudad (lógica existente)
            if not ctx.get("ciudad"):
                ciudades = ["guatemala", "mixco", "capital", "villa nueva", "escuintla",
                            "jalapa", "chimaltenango", "chiquimula", "sacatepéquez",
                            "sololá", "quetzaltenango", "retalhuleu", "suchitepéquez"]
                for ciudad in ciudades:
                    if ciudad in ultimo_mensaje:
                        ctx["ciudad"] = ciudad.capitalize()
                        if ctx.get("requiere_auditoria_electrica"):
                            ctx["empresa_electrica"] = "EEGSA"
                            ctx["tarifa_base_gtq"] = 1.45
                        break

            # Topología (lógica existente)
            if not ctx.get("topologia"):
                if any(k in ultimo_mensaje for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
                    ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
                    ctx["requiere_auditoria_electrica"] = True
                elif any(k in ultimo_mensaje for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                    ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
                    ctx["requiere_auditoria_electrica"] = True

        # --- PREGUNTAS GUIADAS ---
        if not ctx.get("whatsapp") or ctx["whatsapp"] == "Pendiente":
            if not ctx.get("preguntando_whatsapp"):
                ctx["preguntando_whatsapp"] = True
                return {"messages": [AIMessage(content="Para poder enviarte la cotización, necesito tu número de WhatsApp con código de país (ej. +502 1234-5678).")], "contexto_tecnico": ctx}
        else:
            ctx["preguntando_whatsapp"] = False

        if not ctx.get("email"):
            if not ctx.get("preguntando_email"):
                ctx["preguntando_email"] = True
                return {"messages": [AIMessage(content="¿A qué correo electrónico te gustaría que te enviemos la cotización?")], "contexto_tecnico": ctx}
        else:
            ctx["preguntando_email"] = False

        if not ctx.get("productos") or len(ctx["productos"]) == 0:
            # === USAR LA ONTOLOGÍA EXISTENTE ===
            productos = buscar_productos_por_mensaje(ultimo_mensaje)
            if productos:
                ctx["productos"] = productos
            else:
                if not ctx.get("preguntando_productos"):
                    ctx["preguntando_productos"] = True
                    return {"messages": [AIMessage(content="¿Qué tipo de sistemas solares te interesan? Por ejemplo: paneles solares, calentadores, bombas de agua, etc.")], "contexto_tecnico": ctx}
        else:
            ctx["preguntando_productos"] = False

        if not ctx.get("vendedor"):
            ctx["vendedor"] = asignar_vendedor(ctx.get("whatsapp"))

        if ctx.get("whatsapp") and ctx["whatsapp"] != "Pendiente":
            _, ctx["whatsapp"] = normalizar_contacto("", ctx["whatsapp"], "")

        # --- PERSISTENCIA (si todos los campos están completos) ---
        if validar_campos_obligatorios(ctx):
            try:
                import asyncio
                thread_id = config.get("configurable", {}).get("thread_id")
                if thread_id:
                    asyncio.run(actualizar_thread(
                        thread_id=thread_id,
                        nombre=ctx["nombre"],
                        whatsapp=ctx["whatsapp"],
                        email=ctx["email"],
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
            except Exception as e:
                logger.error(f"Error al persistir datos del cliente: {e}")

        # --- CONTINUAR CON EL FLUJO NORMAL DEL CHATBOT ---
        if ctx.get("requiere_auditoria_electrica"):
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
        else:
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación y Necesidad exacta."

        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get("topologia"))

        nombre_ctx = ctx.get("nombre", "Usuario")
        whatsapp_ctx = ctx.get("whatsapp", "Pendiente")
        nombre_run, whatsapp_run = normalizar_contacto(nombre_ctx, whatsapp_ctx, ctx.get("ciudad", ""))

        config["run_name"] = f"Lead: {nombre_run}"
        if "metadata" not in config:
            config["metadata"] = {}
        config["metadata"]["whatsapp"] = whatsapp_run
        config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
        config["metadata"]["vendedor"] = ctx.get("vendedor", "gerencia@aisa.com.gt")

        prompt_sistema = SystemMessage(
            content=(
                f"Eres Jarvi, Ingeniero de Preventa de AISA Solar.\n"
                f"Responde con los datos auditados:\n"
                f"- Ubicación: {ctx.get('ciudad', 'PENDIENTE')}\n"
                f"- Distribuidora: {ctx.get('empresa_electrica', 'PENDIENTE')}\n"
                f"- Tarifa: GTQ {ctx.get('tarifa_base_gtq', 'PENDIENTE')} /kWh\n"
                f"REGLAS: {regla_datos}\n"
                f"ONTOLOGÍA: {ontologia_dinamica}\n"
                f"Cliente: {ctx.get('nombre', 'PENDIENTE')} | WhatsApp: {ctx.get('whatsapp', 'PENDIENTE')} | Email: {ctx.get('email', 'PENDIENTE')}\n"
                f"Productos de interés: {', '.join(ctx.get('productos', ['PENDIENTE']))}\n"
                f"Vendedor asignado: {ctx.get('vendedor', 'PENDIENTE')}"
            )
        )

        respuesta = llm.invoke([prompt_sistema] + state["messages"], config=config)
        logger.info(f"[chatbot] contexto después de LLM: {ctx}")
        return {"messages": [respuesta], "contexto_tecnico": ctx}

    # -------------------- Ensamblaje del grafo --------------------
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

# ---------------------------------------------------------------------------
# Exportación para LangGraph Studio
# ---------------------------------------------------------------------------
from langgraph.checkpoint.memory import MemorySaver

checkpointer_studio = MemorySaver()
jarvi_graph = create_graph(checkpointer_studio)
