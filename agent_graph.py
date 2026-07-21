"""
agent_graph.py
═══════════════════════════════════════════════════════════════════════
Grafo agéntico con instrumentación OpenTelemetry y atributos semánticos gen_ai.*
"""
import os, time, uuid, asyncio, threading, requests, re, functools, logging
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
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.base import BaseCheckpointSaver

# OpenTelemetry
from telemetry_otel import get_tracer
from opentelemetry.trace import Status, StatusCode
from utils.sanitize import sanitize_pii, sanitize_dict

import config
from audit import auditar_fase
from ontology import obtener_fragmento_ontologia, cargar_ontologia, obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion

logger = logging.getLogger(__name__)
tracer = get_tracer("jarvi.graph")

# =============================================================================
# CONFIGURACIÓN (sin cambios)
# =============================================================================
OPENAI_KEYS = [os.getenv(f"OPENAI_API_KEY_{i}") for i in range(1, 4)]
OPENAI_KEYS = [k for k in OPENAI_KEYS if k]
DEFAULT_API_KEY = OPENAI_KEYS[0] if OPENAI_KEYS else os.getenv("OPENAI_API_KEY")
if not DEFAULT_API_KEY:
    raise RuntimeError("No se encontró ninguna API Key de OpenAI.")

CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}

def normalizar_contacto(nombre_raw, whatsapp_raw, ubicacion_raw):
    # (código sin cambios, igual que en tu versión original)
    # ... (se mantiene exactamente igual)
    pass

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

def observe_node(layer: str = "graph", node_name: str = ""):
    # (código sin cambios)
    pass

# =============================================================================
# HERRAMIENTA CONVERTIDA A ASYNC
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
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
    with tracer.start_as_current_span("dispatch_lead") as span:
        span.set_attribute("channel", "email+webhook")
        span.set_attribute("whatsapp", whatsapp_norm)
        span.set_attribute("nombre", nombre_norm)
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.operation", "dispatch")

        async def tarea_background():
            num_limpio = ''.join(filter(str.isdigit, whatsapp_norm))
            try:
                msg = MIMEMultipart()
                msg['To'] = config.CONTROLLER_EMAIL
                msg['From'] = config.SMTP_USER
                msg['Subject'] = resumen_18_palabras
                cuerpo = (
                    f"Oportunidad Validada por Auditoría ISO:\n\n"
                    f"Cliente: {nombre_norm}\nWhatsApp: {whatsapp_norm}\n"
                    f"Ubicación: {departamento_municipio}\nConsumo: {consumo_actual}\n"
                    f"Distribuidora: {empresa_electrica}\nEspecificación: {definicion_necesidad}\n\n"
                    f"Equipos Propuestos:\n{listado_equipos_html}"
                )
                msg.attach(MIMEText(cuerpo, 'plain'))
                creds = Credentials(
                    token=None,
                    refresh_token=os.getenv("GMAIL_REFRESH_TOKEN"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.getenv("GMAIL_CLIENT_ID"),
                    client_secret=os.getenv("GMAIL_CLIENT_SECRET")
                )
                service = build('gmail', 'v1', credentials=creds)
                raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
                service.users().messages().send(userId="me", body={'raw': raw}).execute()
            except Exception as e:
                logger.error(f"Fallo en envío de correo: {e}")

            payload_wa = {
                "instance_id": os.getenv("APICHAT_INSTANCE", ""),
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
                    os.getenv("APICHAT_ENDPOINT", ""),
                    json=payload_wa,
                    headers={
                        "Authorization": f"Bearer {os.getenv('APICHAT_TOKEN', '')}",
                        "Content-Type": "application/json"
                    },
                    timeout=15
                )
            except Exception as e:
                logger.error(f"Fallo en envío de webhook: {e}")

        asyncio.create_task(tarea_background())
        span.set_status(Status(StatusCode.OK))
        return f"✅ Los datos técnicos han sido guardados y auditados. Contacto: {whatsapp_norm}."

# =============================================================================
# FUNCIONES AUXILIARES Y DECORADOR (sin cambios)
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
    def decorator(func):
        @functools.wraps(func)
        def wrapper(state, config=None):
            with tracer.start_as_current_span(node_name) as span:
                span.set_attribute("node.name", node_name)
                span.set_attribute("gen_ai.system", "openai")
                span.set_attribute("gen_ai.operation", node_name)
                result = func(state, config) if config is not None else func(state)
                if isinstance(result, dict) and "contexto_tecnico" in result:
                    ctx = result["contexto_tecnico"]
                    if ctx.get("topologia"):
                        span.set_attribute("topologia", ctx["topologia"])
                    if ctx.get("tipo_producto"):
                        span.set_attribute("tipo_producto", ctx["tipo_producto"])
                span.set_status(Status(StatusCode.OK))
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

    @auditar_fase(...)
    @observe_node(...)
    @otel_span_node("clasificar_intencion_comercial")
    def clasificar_intencion_comercial_node(state: AgentState):
        # (código sin cambios)
        pass

    @auditar_fase(...)
    @observe_node(...)
    @otel_span_node("validar_ubicacion_cliente")
    def validar_ubicacion_cliente_node(state: AgentState):
        # (código sin cambios)
        pass

    @auditar_fase(...)
    @observe_node(...)
    @otel_span_node("seleccionar_productos")
    def seleccionar_productos_node(state: AgentState):
        # (código sin cambios)
        pass

    # NODO LLM CON SPAN Y ATRIBUTOS SEMÁNTICOS
    @auditar_fase(nombre_fase="Generación de Respuesta Comercial", criticidad="ALTA")
    @observe_node(node_name="generar_respuesta_comercial")
    @otel_span_node("generar_respuesta_comercial")
    def generar_respuesta_comercial_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # (código de extracción de nombre, ubicación, etc. – sin cambios)
        # ... (todo el código de preparación del prompt)

        with tracer.start_as_current_span("llm_generation") as llm_span:
            llm_span.set_attribute("gen_ai.system", "openai")
            llm_span.set_attribute("gen_ai.operation", "chat")
            llm_span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
            llm_span.set_attribute("gen_ai.request.temperature", 0.1)

            prompt_text = prompt_sistema.content + " " + ultimo_mensaje
            llm_span.set_attribute("gen_ai.prompt.0.role", "system")
            llm_span.set_attribute("gen_ai.prompt.0.content", sanitize_pii(prompt_text[:5000]))

            respuesta = llm.invoke([prompt_sistema] + state["messages"], config=config)

            llm_span.set_attribute("gen_ai.completion.0.role", "assistant")
            llm_span.set_attribute("gen_ai.completion.0.content", sanitize_pii(respuesta.content[:5000]))

            if hasattr(respuesta, 'response_metadata'):
                usage = respuesta.response_metadata.get('token_usage', {})
                llm_span.set_attribute("gen_ai.usage.input_tokens", usage.get('prompt_tokens', 0))
                llm_span.set_attribute("gen_ai.usage.output_tokens", usage.get('completion_tokens', 0))
                llm_span.set_attribute("gen_ai.usage.total_tokens", usage.get('total_tokens', 0))

            llm_span.set_status(Status(StatusCode.OK))

        return {"messages": [respuesta], "contexto_tecnico": ctx}

    # Nodo anexar caso (sin cambios)
    @observe_node(...)
    @otel_span_node("anexar_caso_respuesta")
    def anexar_caso_respuesta_node(state: AgentState, config: RunnableConfig):
        # (código sin cambios)
        pass

    # Ensamblaje (sin cambios)
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
