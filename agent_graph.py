"""
agent_graph.py
Módulo central del grafo agéntico de JARVI 2.0.
Contiene la definición del estado compartido, herramientas, nodos de razonamiento
y la función de construcción del grafo con persistencia en PostgreSQL.
Incorpora el decorador CTFOM de telemetría cognitiva para la observabilidad
de cada nodo del grafo (trazas, latencia, errores).

Estándares: ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
"""

import os
import time
import uuid
import threading
import requests
import re
import functools
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
from ontology import obtener_fragmento_ontologia, cargar_ontologia, get_product_blocks
# --- CTFOM: módulo de telemetría cognitiva ---
from telemetry import trace_id_var, span_id_var, parent_span_id_var, schedule_telemetry_event
# --- Nuevo módulo de ubicación ---
from ubicacion import buscar_ubicacion

# =============================================================================
# Configuración de API Key (compatible con OPENAI_API_KEY_1, _2, _3)
# CAPA DE RESILIENCIA: Permite fallback entre múltiples claves de OpenAI.
# =============================================================================
OPENAI_KEYS = [os.getenv(f"OPENAI_API_KEY_{i}") for i in range(1, 4)]
OPENAI_KEYS = [k for k in OPENAI_KEYS if k]
DEFAULT_API_KEY = OPENAI_KEYS[0] if OPENAI_KEYS else os.getenv("OPENAI_API_KEY")
if not DEFAULT_API_KEY:
    raise RuntimeError("No se encontró ninguna API Key de OpenAI.")

# ---------------------------------------------------------------------------
# Diccionario de códigos de área para Centroamérica
# Prueba de caja negra: Inyectar ubicaciones con nombres de países y verificar
# que se asigna el código correcto.
# ---------------------------------------------------------------------------
CODIGOS_AREA = {
    "belice": "+501", "costa rica": "+506", "el salvador": "+503",
    "guatemala": "+502", "honduras": "+504", "nicaragua": "+505",
    "panama": "+507", "panamá": "+507"
}


def normalizar_contacto(nombre_raw: str, whatsapp_raw: str, ubicacion_raw: str) -> tuple:
    """
    Normaliza el nombre, el número de WhatsApp y el código de área del cliente.

    Parámetros:
        nombre_raw (str): nombre tal cual fue extraído.
        whatsapp_raw (str): número de teléfono en cualquier formato.
        ubicacion_raw (str): texto que podría contener un país.

    Retorna:
        tuple: (nombre_normalizado, whatsapp_formateado)

    Prueba de caja negra (ISO/IEC 29119):
        - Entrada: ("José", "12345678", "guatemala") -> ("José", "+502 1234-5678")
        - Entrada: ("maria", "87654321", "honduras") -> ("Maria", "+504 8765-4321")
        - Entrada: ("", "50212345678", "Guatemala") -> ("Usuario", "+502 1234-5678")
    """
    nombre_str = str(nombre_raw).strip() if nombre_raw else "Usuario"
    nombre_partes = nombre_str.split()
    nombre_normalizado = " ".join([p.capitalize() for p in nombre_partes]) if nombre_partes else "Usuario"

    # Determinación del código de área a partir de la ubicación
    codigo_area = "+502"  # Guatemala por defecto
    ubicacion_lower = str(ubicacion_raw).lower() if ubicacion_raw else ""
    for pais, codigo in CODIGOS_AREA.items():
        if pais in ubicacion_lower:
            codigo_area = codigo
            break

    # Limpieza y formateo del número de WhatsApp
    whatsapp_str = str(whatsapp_raw) if whatsapp_raw else ""
    digits = re.sub(r'\D', '', whatsapp_str)
    if not digits:
        whatsapp_formateado = "Pendiente"
    else:
        codigo_limpio = codigo_area.replace('+', '')
        # Si el número ya incluye el código de área, lo extraemos
        if digits.startswith(codigo_limpio) and len(digits) > len(codigo_limpio) + 5:
            base = digits[len(codigo_limpio):]
        else:
            base = digits
        if len(base) >= 8:
            whatsapp_formateado = f"{codigo_area} {base[:4]}-{base[4:]}"
        else:
            whatsapp_formateado = f"{codigo_area} {base}"
    return nombre_normalizado, whatsapp_formateado


# ---------------------------------------------------------------------------
# Esquemas de datos para extracción de contacto y contexto técnico
# ---------------------------------------------------------------------------
class ExtractorContacto(BaseModel):
    """Esquema de salida estructurada para identificar nombre y teléfono."""
    nombre: Optional[str] = Field(None, description="Nombre de pila y apellidos.")
    telefono: Optional[str] = Field(None, description="Número telefónico.")


class InferenciaEnergetica(TypedDict):
    """Estructura del contexto técnico que persiste durante toda la conversación."""
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool
    requiere_auditoria_electrica: bool
    nombre: Optional[str]
    whatsapp: Optional[str]
    # Nuevos campos
    departamento: Optional[str]
    municipio: Optional[str]
    vendedor: Optional[str]
    productos_interes: Optional[list]


class AgentState(TypedDict):
    """Estado global del agente: historial de mensajes y contexto técnico."""
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica


# ---------------------------------------------------------------------------
# Decorador CTFOM para nodos del grafo (telemetría cognitiva)
# ---------------------------------------------------------------------------
def observe_node(layer: str = "graph", node_name: str = ""):
    """
    Decorador síncrono que envuelve funciones del grafo para registrar eventos
    de telemetría (inicio/fin/error) con trace_id, span_id, latencia, etc.

    Requiere que el contexto de traza haya sido inicializado (desde el middleware HTTP).
    Agenda la telemetria sin bloquear el flujo del grafo.
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
                # Registrar evento exitoso de forma asíncrona no bloqueante
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


# ---------------------------------------------------------------------------
# Herramienta de persistencia de oportunidades comerciales
# ---------------------------------------------------------------------------
@tool
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
        """Ejecuta el envío de notificaciones en segundo plano para no bloquear el flujo principal."""
        num_limpio = ''.join(filter(str.isdigit, whatsapp_norm))
        # ----- Envío de correo mediante Gmail API -----
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
            print(f"Fallo en envío de correo: {e}")

        # ----- Envío de mensaje por WhatsApp (webhook) -----
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
            print(f"Fallo en envío de webhook: {e}")

    # Ejecución en hilo separado para no bloquear la respuesta al usuario
    threading.Thread(target=tarea_background).start()
    return f"✅ Los datos técnicos han sido guardados y auditados. Contacto: {whatsapp_norm}."


def extraer_intencion_humana(messages: list) -> str:
    """
    Extrae el último mensaje de texto enviado por el usuario.

    Parámetros:
        messages (list): lista de mensajes del estado del grafo.

    Retorna:
        str: contenido textual del último mensaje humano, en minúsculas.

    Prueba de caja negra:
        - Si el último mensaje es HumanMessage con contenido de texto, retorna ese texto.
        - Si es de tipo lista (multimodal), concatena los fragmentos de texto.
        - Si no hay mensaje humano, retorna cadena vacía.
    """
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


# ---------------------------------------------------------------------------
# Función para obtener productos relevantes (Nueva)
# ---------------------------------------------------------------------------
def obtener_productos_relevantes(topologia: str, max_items: int = 5) -> list:
    """
    Retorna una lista de hasta max_items productos de la ontología
    que corresponden a la topología detectada.
    """
    ontologia = cargar_ontologia()
    bloques = get_product_blocks(topologia)
    productos = []
    for bid in bloques[:max_items]:
        if bid in ontologia:
            item = ontologia[bid]
            productos.append({
                "nombre": item["nombre"],
                "tag": item["tag"],
                "url": item["url"]
            })
    return productos


# ---------------------------------------------------------------------------
# Construcción del grafo del agente
# ---------------------------------------------------------------------------
def create_graph(checkpointer: BaseCheckpointSaver):
    """
    Crea y compila el grafo de estados del agente JARVI.

    Parámetros:
        checkpointer (BaseCheckpointSaver): instancia de persistencia (AsyncPostgresSaver).

    Retorna:
        CompiledStateGraph: grafo compilado listo para invocar.

    Prueba de caja negra (ISO/IEC 29119):
        - Inyectar una secuencia de mensajes y verificar que el estado
          'contexto_tecnico' se actualice correctamente tras cada nodo.
        - Comprobar que la herramienta de persistencia se invoca solo cuando el LLM
          decide llamarla (tools_condition).
    """
    graph_builder = StateGraph(AgentState)

    # Modelo de lenguaje principal (GPT-4o mini) con la herramienta de persistencia
    # Uso de DEFAULT_API_KEY (resiliencia con OPENAI_API_KEY_1, _2, _3)
    llm = ChatOpenAI(openai_api_key=DEFAULT_API_KEY, model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # -------------------- Nodo: Clasificador Topológico --------------------
    @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
    @observe_node(node_name="clasificador_topologia")
    def clasificador_topologia_node(state: AgentState):
        """
        Infiere la topología del sistema (On‑Grid / Off‑Grid) a partir
        de las palabras clave detectadas en el último mensaje del usuario.
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

    # -------------------- Nodo: Validador Geográfico --------------------
    @auditar_fase(nombre_fase="Validador Geográfico", criticidad="MEDIA")
    @observe_node(node_name="validador_geolocalizacion")
    def validador_geolocalizacion_node(state: AgentState):
        """
        Determina la ciudad, departamento y municipio basándose en la ubicación detectada.
        Usa el módulo ubicacion.py que hace matching fuzzy con el JSON de municipios.
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
                import logging
                logging.getLogger("jarvi.agent").info(f"Ubicación detectada: {resultado['label']}")

        if ctx.get("requiere_auditoria_electrica") and ctx.get("departamento"):
            if ctx["departamento"].lower() == "guatemala":
                ctx["empresa_electrica"] = "EEGSA"
                ctx["tarifa_base_gtq"] = 1.45

        return {"contexto_tecnico": ctx}

    # -------------------- Nodo: Chatbot (Inferencia principal) --------------------
    @auditar_fase(nombre_fase="Inferencia del Chatbot", criticidad="ALTA")
    @observe_node(node_name="chatbot")
    def chatbot_node(state: AgentState, config: RunnableConfig):
        """
        Nodo central que invoca al LLM con el contexto enriquecido.
        También intenta extraer nombre, teléfono y vendedor.
        """
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # Extracción de contacto vía modelo estructurado
        if ultimo_mensaje and (not ctx.get("nombre") or ctx.get("nombre") == "Usuario" or not ctx.get("whatsapp")):
            try:
                extraccion = extractor_llm.invoke(f"Identifica nombre o teléfono. Mensaje: {ultimo_mensaje}")
                if extraccion.nombre and (not ctx.get("nombre") or ctx["nombre"] == "Usuario"):
                    ctx["nombre"] = extraccion.nombre
                if extraccion.telefono and (not ctx.get("whatsapp") or ctx["whatsapp"] == "Pendiente"):
                    ctx["whatsapp"] = extraccion.telefono
            except Exception:
                pass

        # Extracción de vendedor mediante expresión regular
        if ultimo_mensaje and not ctx.get("vendedor"):
            vendedor_match = re.search(r'(?:mi\s+vendedor\s+es|vendedor[:]\s*)([A-Za-z0-9\s]+)', ultimo_mensaje, re.IGNORECASE)
            if vendedor_match:
                ctx["vendedor"] = vendedor_match.group(1).strip()

        # Reglas de recolección de datos según topología
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

        prompt_sistema = SystemMessage(
            content=(
                f"Eres Jarvi, Ingeniero de Preventa de AISA Solar. "
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
# PASO 1: Exportación limpia para LangGraph Studio (Servicio Visualizador)
# ---------------------------------------------------------------------------
# Se protege la creación del grafo para evitar errores al importar.
if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer_studio = MemorySaver()
    jarvi_graph = create_graph(checkpointer_studio)
else:
    jarvi_graph = None
