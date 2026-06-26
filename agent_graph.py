import streamlit as st
import threading
import requests
import re
from typing import Annotated, TypedDict, Optional
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
from ontology import obtener_fragmento_ontologia

# --- Diccionario y Motor de Normalización (Tu lógica original intacta) ---
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

# --- Esquemas (Tu propiedad intelectual de telemetría y auditoría) ---
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

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica

# --- Herramienta de Persistencia (Inalterada) ---
@tool
@auditar_fase(nombre_fase="Herramienta Persistencia Oportunidades", criticidad="ALTA")
def procesar_oportunidad_backend(nombre_apellidos: str, departamento_municipio: str, consumo_actual: str, empresa_electrica: str, definicion_necesidad: str, listado_equipos_html: str, numero_whatsapp: str, resumen_18_palabras: str) -> str:
    """Envía de forma asíncrona los leads estructurados capturados por la IA hacia los canales del Controller."""
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
    
    def tarea_background():
        num_limpio = ''.join(filter(str.isdigit, whatsapp_norm))
        try:
            msg = MIMEMultipart()
            msg['To'] = config.CONTROLLER_EMAIL
            msg['From'] = config.SMTP_USER
            msg['Subject'] = resumen_18_palabras
            cuerpo = f"Oportunidad Validada por Auditoría ISO:\n\nCliente: {nombre_norm}\nWhatsApp: {whatsapp_norm}\nUbicación: {departamento_municipio}\nConsumo: {consumo_actual}\nDistribuidora: {empresa_electrica}\nEspecificación: {definicion_necesidad}\n\nEquipos Propuestos:\n{listado_equipos_html}"
            msg.attach(MIMEText(cuerpo, 'plain'))
            creds = Credentials(token=None, refresh_token=config.os.getenv("GMAIL_REFRESH_TOKEN"), token_uri="https://oauth2.googleapis.com/token", client_id=config.os.getenv("GMAIL_CLIENT_ID"), client_secret=config.os.getenv("GMAIL_CLIENT_SECRET"))
            service = build('gmail', 'v1', credentials=creds)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
            service.users().messages().send(userId="me", body={'raw': raw}).execute()
        except Exception as e:
            print(f"Fallo en envío de correo: {e}")
        payload_wa = {"instance_id": config.APICHAT_INSTANCE, "number": num_limpio, "text": f"🚨 Lead Calificado:\n\nCliente: {nombre_norm}\nWhatsApp: {whatsapp_norm}\nUbicación: {departamento_municipio}\nEquipos:\n{listado_equipos_html}"}
        try:
            requests.post(config.APICHAT_ENDPOINT, json=payload_wa, headers={"Authorization": f"Bearer {config.APICHAT_TOKEN}", "Content-Type": "application/json"}, timeout=15)
        except Exception as e:
            print(f"Fallo en envío de webhook: {e}")

    threading.Thread(target=tarea_background).start()
    return f"✅ Los datos técnicos han sido guardados y auditados. Contacto: {whatsapp_norm}."

def extraer_intencion_humana(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str): return msg.content.lower()
            if isinstance(msg.content, list): return " ".join([str(b.get("text", "")).lower() for b in msg.content if isinstance(b, dict) and "text" in b])
    return ""

# --- Construcción del Grafo (Refactorizado para inyectar checkpointer) ---
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
    def clasificador_topologia_node(state: AgentState):
        ctx = state.get("contexto_tecnico", {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo: return {"contexto_tecnico": ctx}
        if not ctx.get("topologia"):
            if any(k in ultimo for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
                ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
                ctx["requiere_auditoria_electrica"] = True
            elif any(k in ultimo for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
                ctx["requiere_auditoria_electrica"] = True
        return {"contexto_tecnico": ctx}

    @auditar_fase(nombre_fase="Validador Geográfico", criticidad="MEDIA")
    def validador_geolocalizacion_node(state: AgentState):
        ctx = state.get("contexto_tecnico", {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo: return {"contexto_tecnico": ctx}
        if not ctx.get("ciudad"):
            if any(k in ultimo for k in ["guatemala", "mixco", "capital", "ciudad", "villa nueva"]):
                ctx["ciudad"] = "Guatemala Metropolitana"
                if ctx.get("requiere_auditoria_electrica"):
                    ctx["empresa_electrica"] = "EEGSA"
                    ctx["tarifa_base_gtq"] = 1.45
        return {"contexto_tecnico": ctx}

    @auditar_fase(nombre_fase="Inferencia del Chatbot", criticidad="ALTA")
    def chatbot_node(state: AgentState, config: RunnableConfig):
        ctx = state.get("contexto_tecnico", {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))
        if ultimo_mensaje and (not ctx.get("nombre") or ctx.get("nombre") == "Usuario" or not ctx.get("whatsapp")):
            try:
                extraccion = extractor_llm.invoke(f"Identifica nombre o teléfono. Mensaje: {ultimo_mensaje}")
                if extraccion.nombre and (not ctx.get("nombre") or ctx["nombre"] == "Usuario"): ctx["nombre"] = extraccion.nombre
                if extraccion.telefono and (not ctx.get("whatsapp") or ctx["whatsapp"] == "Pendiente"): ctx["whatsapp"] = extraccion.telefono
            except Exception: pass
        regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta." if ctx.get("requiere_auditoria_electrica") else "1. DEBES recopilar sutilmente: Nombre, Ubicación y Necesidad exacta."
        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))
        nombre_ctx = ctx.get("nombre", "Usuario")
        whatsapp_ctx = ctx.get("whatsapp", "Pendiente")
        nombre_run, whatsapp_run = normalizar_contacto(nombre_ctx, whatsapp_ctx, ctx.get("ciudad", ""))
        config["run_name"] = f"Lead: {nombre_run}"
        if "metadata" not in config: config["metadata"] = {}
        config["metadata"]["whatsapp"] = whatsapp_run
        config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
        prompt_sistema = SystemMessage(content=f"Eres Jarvi, Ingeniero de Preventa de AISA Solar. Responde con los datos auditados:\n- Ubicación: {ctx.get('ciudad', 'PENDIENTE')}\n- Distribuidora: {ctx.get('empresa_electrica', 'PENDIENTE')}\n- Tarifa: GTQ {ctx.get('tarifa_base_gtq', 'PENDIENTE')} /kWh\nREGLAS: {regla_datos}\nONTOLOGÍA: {ontologia_dinamica}")
        return {"messages": [llm.invoke([prompt_sistema] + state["messages"], config=config)], "contexto_tecnico": ctx}

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
