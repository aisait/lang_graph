"""
agent_graph.py - Grafo agéntico de JARVI 2.0 con 6 pasos y selección de productos.

OBSERVABILIDAD (ISO/IEC 25010, DORA):
- Se integra Langfuse mediante decorador @observe para trazabilidad de nodos y herramientas.
- Se elimina dependencia de LangSmith (sustituido por Langfuse).
- CTFOM (telemetry.py) se mantiene para métricas de infraestructura.

ESTÁNDARES APLICADOS:
- ISO/IEC 25010:2011 (Calidad del producto) – Fiabilidad, Mantenibilidad
- ISO/IEC 29119:2022 (Pruebas) – Pruebas de caja negra documentadas
- ISO/IEC 27001:2022 (Seguridad) – Gestión de secretos, trazabilidad de acceso
- DORA (EU) – Resiliencia operacional, registro de incidentes

PRUEBAS DE CAJA NEGRA (ISO/IEC 29119):
    1. Ejecutar nodo de clasificación → traza aparece en Langfuse como observation
    2. Ejecutar herramienta procesar_oportunidad_backend → observation tipo SPAN
    3. Error en nodo → error capturado con código y mensaje
    4. Verificar que los nombres de nodos son semánticos (negocio)
"""

import os
import time
import uuid
import threading
import requests
import re
import functools
import logging
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

import config
from audit import auditar_fase
from ontology import obtener_fragmento_ontologia, cargar_ontologia, obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion

# Observabilidad: Langfuse (reemplaza a LangSmith)
from langfuse.decorators import observe

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACIÓN DE API KEY (compatible con OPENAI_API_KEY_1, _2, _3)
# =============================================================================
OPENAI_KEYS = [os.getenv(f"OPENAI_API_KEY_{i}") for i in range(1, 4)]
OPENAI_KEYS = [k for k in OPENAI_KEYS if k]
DEFAULT_API_KEY = OPENAI_KEYS[0] if OPENAI_KEYS else os.getenv("OPENAI_API_KEY")
if not DEFAULT_API_KEY:
    raise RuntimeError("No se encontró ninguna API Key de OpenAI.")

# =============================================================================
# CÓDIGOS DE ÁREA CENTROAMÉRICA
# =============================================================================
CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}

def normalizar_contacto(nombre_raw: str, whatsapp_raw: str, ubicacion_raw: str) -> tuple:
    """
    Normaliza nombre y número de WhatsApp con código de área del país detectado.
    Prueba de caja negra (ISO/IEC 29119):
        1. nombre_raw = "juan perez", whatsapp_raw = "12345678", ubicacion_raw = "Guatemala"
           → ("Juan Perez", "+502 1234-5678")
        2. Sin número → ("Usuario", "Pendiente")
        3. País no detectado → código por defecto +502
    """
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
# ESQUEMAS DE DATOS
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
# DECORADOR CTFOM (Telemetría de infraestructura)
# =============================================================================
def observe_node(layer: str = "graph", node_name: str = ""):
    """
    Decorador para telemetría CTFOM (CPU, memoria, latencia).
    Se mantiene para métricas de infraestructura.
    Langfuse se añade mediante @observe separado.
    """
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
# HERRAMIENTA DE PERSISTENCIA DE OPORTUNIDADES (CON LANGfuse)
# =============================================================================
@tool
@observe(as_type="span")  # <-- LANGfuse: traza la herramienta como un span
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
    """
    Envía de forma asíncrona los leads estructurados capturados por la IA
    hacia los canales del Controller (correo Gmail y webhook de WhatsApp).

    Prueba de caja negra (ISO/IEC 29119):
        - Verificar que se envíe un correo al Controller y un mensaje de WhatsApp
          usando los parámetros de entrada.
        - Verificar que, aunque falle uno de los canales, el otro se ejecute.
        - La herramienta debe retornar un mensaje de éxito incluyendo el contacto normalizado.
    """
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
    
    def tarea_background():
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
            requests.post(
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
    
    threading.Thread(target=tarea_background).start()
    return f"✅ Los datos técnicos han sido guardados y auditados. Contacto: {whatsapp_norm}."

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

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO (CON NOMBRES SEMÁNTICOS)
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = ChatOpenAI(openai_api_key=DEFAULT_API_KEY, model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # -------------------- Nodo: Clasificador de Intención Comercial --------------------
    @auditar_fase(nombre_fase="Clasificador de Intención Comercial", criticidad="MEDIA")
    @observe_node(node_name="clasificar_intencion_comercial")
    @observe()  # <-- LANGfuse: traza este nodo como una observación
    def clasificar_intencion_comercial_node(state: AgentState):
        """
        Infiere la intención del cliente (On-Grid/Off-Grid) basado en el mensaje.
        Prueba de caja negra (ISO/IEC 29119):
            1. Mensaje con "red" o "atado" → topología On-Grid
            2. Mensaje con "aislado" o "batería" → topología Off-Grid
            3. Mensaje sin palabras clave → no establece topología
        """
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

    # -------------------- Nodo: Validador de Ubicación del Cliente --------------------
    @auditar_fase(nombre_fase="Validador de Ubicación del Cliente", criticidad="MEDIA")
    @observe_node(node_name="validar_ubicacion_cliente")
    @observe()  # <-- LANGfuse
    def validar_ubicacion_cliente_node(state: AgentState):
        """
        Valida y enriquece la ubicación del cliente usando fuzzy matching.
        Prueba de caja negra:
            1. Mensaje con "zona 10 Guatemala" → departamento Guatemala, municipio Guatemala
            2. Mensaje sin ubicación → no modifica el contexto
        """
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

    # -------------------- Nodo: Selección de Productos --------------------
    @auditar_fase(nombre_fase="Selección de Productos", criticidad="ALTA")
    @observe_node(node_name="seleccionar_productos")
    @observe()  # <-- LANGfuse
    def seleccionar_productos_node(state: AgentState):
        """
        Determina si el cliente busca sistema completo o producto unitario,
        y selecciona los productos relevantes de la ontología.
        Prueba de caja negra:
            1. Mensaje con "sistema" → tipo_producto = "sistema"
            2. Mensaje con "panel" → tipo_producto = "unitario"
            3. Sin palabras clave → pregunta al cliente
        """
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

    # -------------------- Nodo: Generación de Respuesta Comercial --------------------
    @auditar_fase(nombre_fase="Generación de Respuesta Comercial", criticidad="ALTA")
    @observe_node(node_name="generar_respuesta_comercial")
    @observe()  # <-- LANGfuse
    def generar_respuesta_comercial_node(state: AgentState, config: RunnableConfig):
        """
        Genera la respuesta final del agente con base en el contexto técnico y la ontología.
        Prueba de caja negra:
            1. Cliente con topología y tipo_producto → respuesta incluye productos seleccionados
            2. Cliente sin datos suficientes → respuesta solicita información
            3. Error en la llamada a LLM → se captura y registra en Langfuse
        """
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # Extración forzada de nombre y número
        if ultimo_mensaje:
            num_match = re.search(r'(\+?[0-9]{1,3}[-.\s]?)?[0-9]{4,10}', ultimo_mensaje)
            if num_match:
                raw_num = num_match.group(0)
                _, num_norm = normalizar_contacto("", raw_num, ctx.get("ciudad", ""))
                if num_norm and num_norm != "Pendiente":
                    ctx["whatsapp"] = num_norm
                    logger.info(f"Extraído número de WhatsApp: {num_norm}")
            name_match = re.search(r'(?:mi\s+nombre\s+es|nombre[:]\s*|me\s+llamo|soy\s+)([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)', 
                                   ultimo_mensaje, re.IGNORECASE)
            if name_match:
                raw_name = name_match.group(1).strip()
                if raw_name and len(raw_name) > 1:
                    ctx["nombre"] = raw_name
                    logger.info(f"Extraído nombre: {raw_name}")

        # Extracción con modelo estructurado (respaldo)
        if ultimo_mensaje and (not ctx.get("nombre") or ctx.get("nombre") == "Usuario" or not ctx.get("whatsapp")):
            try:
                extraccion = extractor_llm.invoke(f"Identifica nombre o teléfono. Mensaje: {ultimo_mensaje}")
                if extraccion.nombre and (not ctx.get("nombre") or ctx["nombre"] == "Usuario"):
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono and (not ctx.get("whatsapp") or ctx["whatsapp"] == "Pendiente"):
                    ctx["whatsapp"] = extraccion.telefono
            except Exception:
                pass

        # Extracción de vendedor
        if ultimo_mensaje and not ctx.get("vendedor"):
            vendedor_match = re.search(r'(?:mi\s+vendedor\s+es|vendedor[:]\s*)([A-Za-z0-9\s]+)', 
                                       ultimo_mensaje, re.IGNORECASE)
            if vendedor_match:
                ctx["vendedor"] = vendedor_match.group(1).strip()

        # Detectar tipo de producto
        if ultimo_mensaje and not ctx.get("tipo_producto"):
            tipo = extraer_tipo_producto(ultimo_mensaje)
            if tipo:
                ctx["tipo_producto"] = tipo

        # Seleccionar productos
        if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
            ctx["productos_interes"] = obtener_productos_relevantes(
                topologia=ctx["topologia"],
                tipo=ctx["tipo_producto"],
                max_items=5
            )
            logger.info(f"Productos seleccionados: {ctx['productos_interes']}")

        # Reglas de recolección de datos
        if ctx.get("requiere_auditoria_electrica"):
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
        else:
            regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación y Necesidad exacta."

        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))

        nombre_ctx = ctx.get("nombre", "Usuario")
        whatsapp_ctx = ctx.get("whatsapp", "Pendiente")
        nombre_run, whatsapp_run = normalizar_contacto(nombre_ctx, whatsapp_ctx, ctx.get("ciudad", ""))

        config["run_name"] = f"Lead: {nombre_run}"
        if "metadata" not in config:
            config["metadata"] = {}
        config["metadata"]["whatsapp"] = whatsapp_run
        config["metadata"]["topologia"] = ctx.get("topologia", "Desconocida")
        if ctx.get("tipo_producto"):
            config["metadata"]["tipo_producto"] = ctx["tipo_producto"]
        if ctx.get("productos_interes"):
            config["metadata"]["productos_tags"] = [p["tag"] for p in ctx["productos_interes"]]

        # System prompt
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

        respuesta = llm.invoke([prompt_sistema] + state["messages"], config=config)
        return {"messages": [respuesta], "contexto_tecnico": ctx}

    # -------------------- Nodo: Anexar Caso a la Respuesta --------------------
    @observe_node(node_name="anexar_caso_respuesta")
    @observe()  # <-- LANGfuse
    def anexar_caso_respuesta_node(state: AgentState, config: RunnableConfig):
        """
        Añade el número de caso al final de la respuesta.
        Prueba de caja negra:
            1. Mensaje sin caso → se añade "[Caso No. {caso}]"
            2. Mensaje ya con caso → no se duplica
        """
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

# =============================================================================
# PUNTO DE ENTRADA PARA STUDIO
# =============================================================================
if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer_studio = MemorySaver()
    jarvi_graph = create_graph(checkpointer_studio)
else:
    jarvi_graph = None
