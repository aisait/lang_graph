"""
agent_graph.py - Módulo central del grafo agéntico de JARVI 2.0.
Implementa flujo de recolección de datos en 5 pasos, failover con 3 API Keys,
acumulación de costo, y extracción temprana en el primer mensaje.
"""
from __future__ import annotations

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
from openai import RateLimitError

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import StructuredTool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.base import BaseCheckpointSaver

import config
from audit import auditar_fase
from ontology import obtener_fragmento_ontologia, buscar_productos_por_mensaje
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event
from db_client import actualizar_thread, registrar_evento_auditoria, acumular_costo_thread, obtener_costo_acumulado
from ubicacion import buscar_ubicacion

# =============================================================================
# CONFIGURACIÓN DE API KEYS Y PRECIOS
# =============================================================================
OPENAI_KEYS = [
    os.getenv("OPENAI_API_KEY_1"),
    os.getenv("OPENAI_API_KEY_2"),
    os.getenv("OPENAI_API_KEY_3")
]
OPENAI_KEYS = [k for k in OPENAI_KEYS if k]
if not OPENAI_KEYS:
    raise RuntimeError("No se encontró ninguna API Key de OpenAI.")

DEFAULT_API_KEY = OPENAI_KEYS[0]
PRICE_INPUT = 0.150
PRICE_OUTPUT = 0.600

def calcular_costo_llm(response) -> float:
    try:
        usage = response.response_metadata.get("token_usage", {})
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        return (prompt * PRICE_INPUT + completion * PRICE_OUTPUT) / 1_000_000
    except Exception:
        return 0.0

def invoke_llm_with_failover(messages, config, model="gpt-4o-mini", temperature=0.1, max_retries=3):
    if not OPENAI_KEYS:
        raise RuntimeError("No hay API Keys")
    last_error = None
    for key in OPENAI_KEYS:
        try:
            llm = ChatOpenAI(api_key=key, model=model, temperature=temperature, max_retries=max_retries)
            response = llm.invoke(messages, config=config)
            costo = calcular_costo_llm(response)
            return response, costo
        except RateLimitError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            continue
    raise last_error or RuntimeError("Todas las claves fallaron.")

# =============================================================================
# VENDEDORES
# =============================================================================
VENDEDORES_PATH = os.path.join(os.path.dirname(__file__), "vendedores.json")

def cargar_vendedores() -> List[Dict[str, Any]]:
    try:
        with open(VENDEDORES_PATH, "r") as f:
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
# NORMALIZACIÓN
# =============================================================================
CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}

def normalizar_contacto(nombre_raw: str, whatsapp_raw: str, ubicacion_raw: str) -> tuple:
    nombre = " ".join([p.capitalize() for p in str(nombre_raw).strip().split()]) if nombre_raw else "Usuario"
    codigo = "+502"
    for pais, cod in CODIGOS_AREA.items():
        if pais in str(ubicacion_raw).lower():
            codigo = cod
            break
    digits = re.sub(r'\D', '', str(whatsapp_raw))
    if not digits:
        return nombre, "Pendiente"
    if digits.startswith('502') and len(digits) > 8:
        base = digits[3:]
    else:
        base = digits
    if len(base) >= 8:
        formateado = f"{codigo} {base[:4]}-{base[4:8]}"
    else:
        formateado = f"{codigo} {base}"
    return nombre, formateado

# =============================================================================
# ESQUEMAS
# =============================================================================
class ExtractorContacto(BaseModel):
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None

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
    paso_actual: int

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
                schedule_telemetry_event(trace_id, span_id, parent, layer, node_name, "END", elapsed)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                schedule_telemetry_event(trace_id, span_id, parent, layer, node_name, "ERROR", elapsed, error_code=f"SWR-{type(e).__name__}")
                raise
            finally:
                span_id_var.set(parent)
        return wrapper
    return decorator

# =============================================================================
# HERRAMIENTA DE PERSISTENCIA
# =============================================================================
@auditar_fase(nombre_fase="Herramienta Persistencia Oportunidades", criticidad="ALTA")
def procesar_oportunidad_backend(
    nombre_apellidos: str,
    departamento_municipio: str,
    consumo_actual: str,
    empresa_electrica: str,
    definicion_necesidad: str,
    listado_equipos_html: str,
    numero_whatsapp: str,
    resumen_18_palabras: str
) -> str:
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
    def tarea():
        num = ''.join(filter(str.isdigit, whatsapp_norm))
        try:
            msg = MIMEMultipart()
            msg['To'] = config.CONTROLLER_EMAIL
            msg['From'] = config.SMTP_USER
            msg['Subject'] = resumen_18_palabras
            cuerpo = (
                f"Lead Validado ISO:\nCliente: {nombre_norm}\nWhatsApp: {whatsapp_norm}\n"
                f"Ubicación: {departamento_municipio}\nConsumo: {consumo_actual}\n"
                f"Distribuidora: {empresa_electrica}\nNecesidad: {definicion_necesidad}\n"
                f"Equipos: {listado_equipos_html}"
            )
            msg.attach(MIMEText(cuerpo, 'plain'))
            creds = Credentials(token=None,
                refresh_token=os.getenv("GMAIL_REFRESH_TOKEN"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GMAIL_CLIENT_ID"),
                client_secret=os.getenv("GMAIL_CLIENT_SECRET"))
            service = build('gmail', 'v1', credentials=creds)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId="me", body={'raw': raw}).execute()
        except Exception as e:
            print(f"Correo falló: {e}")
        try:
            requests.post(os.getenv("APICHAT_ENDPOINT", ""),
                json={"instance_id": os.getenv("APICHAT_INSTANCE", ""), "number": num, "text": f"Lead: {nombre_norm} {whatsapp_norm}"},
                headers={"Authorization": f"Bearer {os.getenv('APICHAT_TOKEN', '')}"}, timeout=15)
        except Exception as e:
            print(f"Webhook falló: {e}")
    threading.Thread(target=tarea).start()
    return f"✅ Lead guardado. Contacto: {whatsapp_norm}"

procesar_oportunidad_tool = StructuredTool.from_function(
    func=procesar_oportunidad_backend,
    name="procesar_oportunidad_backend",
    description="Envía el lead al backend por correo y WhatsApp",
)

def extraer_intencion_humana(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                return msg.content.lower()
            elif isinstance(msg.content, list):
                textos = [item.get("text", "") for item in msg.content if isinstance(item, dict) and "text" in item]
                return " ".join(textos).lower()
    return ""

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)

    llm = ChatOpenAI(api_key=DEFAULT_API_KEY, model="gpt-4o-mini", temperature=0.1, max_retries=3).bind_tools([procesar_oportunidad_tool])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # ---------- Nodo: Clasificador Topológico ----------
    @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
    @observe_node(node_name="clasificador_topologia")
    def clasificador_topologia_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo or ctx.get("topologia"):
            return {"contexto_tecnico": ctx}
        if any(k in ultimo for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
            ctx["topologia"] = "On-Grid"
            ctx["requiere_auditoria_electrica"] = True
        elif any(k in ultimo for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
            ctx["topologia"] = "Off-Grid"
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

    # ---------- Nodo: Chatbot (extracción temprana) ----------
    @auditar_fase(nombre_fase="Inferencia del Chatbot", criticidad="ALTA")
    @observe_node(node_name="chatbot")
    def chatbot_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))
        logger = logging.getLogger("jarvi.agent")
        if "paso_actual" not in ctx:
            ctx["paso_actual"] = 0

        # --- EXTRACCIÓN SIEMPRE (incluso primera interacción) ---
        if ultimo_mensaje:
            # 1. LLM + regex para nombre, teléfono, email
            try:
                extraccion = extractor_llm.invoke(
                    f"Del mensaje extrae nombre (campo 'nombre'), teléfono (campo 'telefono') y email (campo 'email'). Mensaje: {ultimo_mensaje}"
                )
                if extraccion.nombre:
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono:
                    _, ctx["whatsapp"] = normalizar_contacto("", extraccion.telefono, "")
                if extraccion.email:
                    ctx["email"] = extraccion.email
            except Exception as e:
                logger.warning(f"LLM extracción falló: {e}")

            # Fallback regex para nombre
            if not ctx.get("nombre"):
                match = re.search(r"(?:me llamo|soy|mi nombre es|nombre:|llamo)\s*([A-Za-záéíóúñ\s]+)", ultimo_mensaje, re.IGNORECASE)
                if match:
                    ctx["nombre"] = match.group(1).strip().title()
            # Fallback regex para teléfono (permite espacios)
            if not ctx.get("whatsapp"):
                match = re.search(r"(\+?[0-9]{1,3}[-.\s]?)?[0-9][\s\-\.]?[0-9]{3,4}[\s\-\.]?[0-9]{3,4}", ultimo_mensaje)
                if match:
                    _, ctx["whatsapp"] = normalizar_contacto("", match.group(0), "")

            # 2. Ubicación (fuzzy matching)
            if not ctx.get("ubicacion"):
                ubicacion = buscar_ubicacion(ultimo_mensaje)
                if ubicacion:
                    ctx["ubicacion"] = ubicacion["label"]
                    ctx["ciudad"] = ubicacion["municipio"]

            # 3. Productos
            if not ctx.get("productos") or len(ctx["productos"]) == 0:
                productos = buscar_productos_por_mensaje(ultimo_mensaje)
                if productos:
                    ctx["productos"] = productos

            # 4. Vendedor
            if not ctx.get("vendedor"):
                vendedor = buscar_vendedor_por_nombre(ultimo_mensaje)
                if vendedor:
                    ctx["vendedor"] = vendedor["email"]

            # 5. Topología
            if not ctx.get("topologia"):
                if any(k in ultimo_mensaje for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
                    ctx["topologia"] = "On-Grid"
                    ctx["requiere_auditoria_electrica"] = True
                elif any(k in ultimo_mensaje for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                    ctx["topologia"] = "Off-Grid"
                    ctx["requiere_auditoria_electrica"] = True

            # 6. Actualizar run_name inmediatamente
            _, whatsapp_run = normalizar_contacto("", ctx.get("whatsapp", "Pendiente"), "")
            if whatsapp_run and whatsapp_run != "Pendiente":
                config["run_name"] = whatsapp_run
                if "metadata" not in config:
                    config["metadata"] = {}
                config["metadata"]["whatsapp"] = whatsapp_run
                config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
                config["metadata"]["vendedor"] = ctx.get("vendedor", "gerencia@aisa.com.gt")
                config["metadata"]["tags"] = ctx.get("productos", [])
                config["metadata"]["ubicacion"] = ctx.get("ubicacion", "PENDIENTE")

            # 7. Avanzar pasos automáticamente
            if ctx.get("nombre") and ctx["paso_actual"] < 2:
                ctx["paso_actual"] = 2
            if ctx.get("whatsapp") and ctx["paso_actual"] < 3:
                ctx["paso_actual"] = 3
            if ctx.get("ubicacion") and ctx["paso_actual"] < 4:
                ctx["paso_actual"] = 4
            if ctx.get("productos") and len(ctx["productos"]) > 0 and ctx["paso_actual"] < 5:
                ctx["paso_actual"] = 5
            if ctx.get("vendedor") and ctx["paso_actual"] < 6:
                ctx["paso_actual"] = 6
            if validar_campos_obligatorios(ctx):
                ctx["paso_actual"] = 6

        # --- Primera interacción: bienvenida personalizada (sin preguntar lo que ya sabemos) ---
        if len(state.get("messages", [])) == 1 and ctx["paso_actual"] == 0:
            # En realidad, si ya tenemos datos, paso_actual ya no es 0, pero por seguridad:
            if not ctx.get("nombre"):
                saludo = "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar."
            else:
                saludo = f"¡Hola {ctx['nombre']}! 👋 Soy Jarvi, tu asesor técnico de AISA Solar."
            bienvenida = saludo + "\n\nPara poder ayudarte mejor, necesito algunos datos:\n"
            if not ctx.get("nombre"):
                bienvenida += "1️⃣ ¿Cómo te llamas?\n"
            if not ctx.get("whatsapp"):
                bienvenida += "2️⃣ ¿Cuál es tu número de WhatsApp?\n"
            if not ctx.get("ubicacion"):
                bienvenida += "3️⃣ ¿De qué municipio y departamento nos hablas?\n"
            if not ctx.get("productos"):
                bienvenida += "4️⃣ ¿Qué productos o sistemas solares te interesan?\n"
            if not ctx.get("vendedor"):
                bienvenida += "5️⃣ ¿Tienes un vendedor asignado?\n"
            if ctx["paso_actual"] == 0:
                ctx["paso_actual"] = 1  # Solo para indicar que ya pasó la primera interacción
            return {"messages": [AIMessage(content=bienvenida)], "contexto_tecnico": ctx}

        # --- Interacciones posteriores: preguntas guiadas según paso_actual ---
        paso = ctx["paso_actual"]

        if paso == 1 and not ctx.get("nombre"):
            return {"messages": [AIMessage(content="¿Cómo te llamas?")], "contexto_tecnico": ctx}
        if paso == 2 and not ctx.get("whatsapp"):
            return {"messages": [AIMessage(content="¿Cuál es tu número de WhatsApp?")], "contexto_tecnico": ctx}
        if paso == 3 and not ctx.get("ubicacion"):
            return {"messages": [AIMessage(content="¿De qué municipio y departamento nos hablas?")], "contexto_tecnico": ctx}
        if paso == 4 and not ctx.get("productos"):
            return {"messages": [AIMessage(content="¿Qué productos o sistemas solares te interesan?")], "contexto_tecnico": ctx}
        if paso == 5 and not ctx.get("vendedor"):
            ctx["vendedor"] = asignar_vendedor_default()
            ctx["paso_actual"] = 6

        # --- Paso 6: responder consultas técnicas ---
        if paso == 6 or validar_campos_obligatorios(ctx):
            ctx["paso_actual"] = 6
            if "metadata" not in config:
                config["metadata"] = {}
            config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
            config["metadata"]["vendedor"] = ctx.get("vendedor", "gerencia@aisa.com.gt")
            config["metadata"]["tags"] = ctx.get("productos", [])
            config["metadata"]["ubicacion"] = ctx.get("ubicacion", "PENDIENTE")
            config["metadata"]["email"] = ctx.get("email", "PENDIENTE")

            if validar_campos_obligatorios(ctx):
                import asyncio
                thread_id = config.get("configurable", {}).get("thread_id")
                if thread_id:
                    asyncio.run(actualizar_thread(
                        thread_id, ctx["nombre"], ctx["whatsapp"], ctx.get("email"),
                        ctx["productos"], ctx["vendedor"], trace_id_var.get()
                    ))
                    asyncio.run(registrar_evento_auditoria(
                        thread_id, trace_id_var.get(), "DATOS_CLIENTE_COMPLETOS", "chatbot_node", ctx
                    ))

            if ctx.get("requiere_auditoria_electrica"):
                regla_datos = "Recopila sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
            else:
                regla_datos = "Recopila sutilmente: Nombre, Ubicación y Necesidad exacta."

            prompt = SystemMessage(
                f"Eres Jarvi, Ingeniero de Preventa de AISA Solar.\n"
                f"Ubicación: {ctx.get('ubicacion', 'PENDIENTE')}\n"
                f"Distribuidora: {ctx.get('empresa_electrica', 'PENDIENTE')}\n"
                f"Tarifa: GTQ {ctx.get('tarifa_base_gtq', 'PENDIENTE')} /kWh\n"
                f"REGLAS: {regla_datos}\n"
                f"ONTOLOGÍA: {obtener_fragmento_ontologia(ctx.get('topologia'))}\n"
                f"Cliente: {ctx.get('nombre', 'PENDIENTE')} | WhatsApp: {ctx.get('whatsapp', 'PENDIENTE')} | Email: {ctx.get('email', 'PENDIENTE')}\n"
                f"Productos: {', '.join(ctx.get('productos', ['PENDIENTE']))}\n"
                f"Vendedor: {ctx.get('vendedor', 'PENDIENTE')}"
            )
            try:
                respuesta, costo = invoke_llm_with_failover([prompt] + state["messages"], config)
                if not respuesta.content:
                    respuesta = AIMessage("Lo siento, no pude generar una respuesta.")
            except Exception as e:
                logger.error(f"LLM falló: {e}")
                respuesta = AIMessage("Error técnico, por favor intenta de nuevo.")
                costo = 0.0

            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id and costo > 0:
                import asyncio
                asyncio.run(acumular_costo_thread(thread_id, costo))
                costo_acum = asyncio.run(obtener_costo_acumulado(thread_id))
                config["metadata"]["cumulative_cost"] = costo_acum

            return {"messages": [respuesta], "contexto_tecnico": ctx}

        # Seguridad: si llegamos aquí sin completar, forzar paso 6
        ctx["paso_actual"] = 6
        return chatbot_node(state, config)

    # ---------- Ensamblaje ----------
    graph_builder.add_node("clasificador", clasificador_topologia_node)
    graph_builder.add_node("validador", validador_geolocalizacion_node)
    graph_builder.add_node("chatbot", chatbot_node)
    graph_builder.add_node("tools", ToolNode([procesar_oportunidad_tool]))
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
