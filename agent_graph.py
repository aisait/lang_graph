"""
agent_graph.py - Grafo agéntico de JARVI 2.0 con instrumentación CTFOM.
VERSIÓN 2.0.20 – Prompts externalizados y lógica de requisitos dinámicos (Ontología Extendida).
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
from typing import Annotated, TypedDict, Optional, List, Dict
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver

# Sanitización
from utils.sanitize import sanitize_pii

import config
from audit import auditar_fase
from ontology import (
    obtener_fragmento_ontologia,
    cargar_ontologia,
    obtener_productos_relevantes,
    inferir_tag_por_mensaje,          # <-- NUEVA FUNCIÓN
    get_requirements_by_tag           # <-- NUEVA FUNCIÓN
)
from telemetry import trace_id_var, span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion

# =============================================================================
# NUEVO: Importar PromptManager para prompts externalizados
# =============================================================================
from prompt_manager import get_prompt

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACIÓN DE API KEY (CON ROTACIÓN)
# =============================================================================
from config import settings

def get_llm():
    return ChatOpenAI(
        openai_api_key=settings.openai_api_key,
        model="gpt-4o-mini",
        temperature=0.1,
        timeout=60.0,
        max_retries=5,
        default_headers={"User-Agent": "JARVI/2.0.17"}
    )

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
# ESQUEMAS (EXTENDIDO CON NUEVOS CAMPOS)
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
    # ===== NUEVOS CAMPOS PARA REQUISITOS DINÁMICOS =====
    product_tag: Optional[str]           # Tag del producto detectado (ej. '1', '11', '19')
    requisitos: Optional[List[Dict]]     # Lista de requisitos del producto
    checklist: Optional[Dict]            # Estado de la checklist (pendiente/completado)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica

# =============================================================================
# DECORADOR CTFOM (MANTENIDO)
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
# HERRAMIENTA DE ENVÍO A N8N (SIN CAMBIOS)
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
    Envía leads calificados a N8N mediante webhook.
    """
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)

    # Obtener endpoint y token
    endpoint = os.getenv("N8N_WEBHOOK_URL", "")
    if not endpoint:
        logger.warning("N8N_WEBHOOK_URL no configurado. Lead no enviado.")
        return "⚠️ No se pudo enviar el lead: webhook no configurado."

    num_limpio = ''.join(filter(str.isdigit, whatsapp_norm))
    payload = {
        "nombre": nombre_norm,
        "whatsapp": num_limpio,
        "ubicacion": departamento_municipio,
        "consumo": consumo_actual,
        "empresa_electrica": empresa_electrica,
        "necesidad": definicion_necesidad,
        "equipos": listado_equipos_html,
        "resumen": resumen_18_palabras
    }

    try:
        await asyncio.to_thread(
            requests.post,
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        logger.info(f"Lead enviado exitosamente a N8N para {whatsapp_norm}")
        return f"✅ Lead enviado a N8N. Contacto: {whatsapp_norm}."
    except Exception as e:
        logger.error(f"Fallo en envío a N8N: {e}")
        return f"❌ Error al enviar lead: {str(e)}"

# =============================================================================
# FUNCIONES AUXILIARES (SIN CAMBIOS)
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

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO (MODIFICADO)
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = get_llm().bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    @auditar_fase(nombre_fase="Clasificador de Intención Comercial", criticidad="MEDIA")
    @observe_node(node_name="clasificar_intencion_comercial")
    async def clasificar_intencion_comercial_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo:
            return {"contexto_tecnico": ctx}
        # Solo se asigna topologia si no viene del producto (respaldo)
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

    # ========================================================================
    # NODO SELECCIONAR PRODUCTOS (NUEVA LÓGICA ONTOLÓGICA)
    # ========================================================================
    @auditar_fase(nombre_fase="Selección de Productos", criticidad="ALTA")
    @observe_node(node_name="seleccionar_productos")
    async def seleccionar_productos_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))

        # 1. Si ya tenemos tag o tipo_producto, no volvemos a preguntar
        if ctx.get("product_tag") or ctx.get("tipo_producto"):
            return {"contexto_tecnico": ctx}

        # 2. Intentar inferir producto del mensaje usando la ontología
        tag = inferir_tag_por_mensaje(ultimo)
        if tag:
            ctx["product_tag"] = tag
            requisitos = get_requirements_by_tag(tag)
            ctx["requisitos"] = requisitos
            # Inicializar checklist
            checklist = {}
            for req in requisitos:
                field = req.get("field")
                if field and ctx.get(field) is not None:
                    checklist[field] = "completado"
                elif field:
                    checklist[field] = "pendiente"
            ctx["checklist"] = checklist
            logger.info(f"Producto detectado: tag={tag}, requisitos={len(requisitos)}")
            return {"contexto_tecnico": ctx}

        # 3. Si no se infiere producto, preguntar al usuario
        pregunta = "¿Sobre qué tipo de equipo le gustaría recibir asesoría? (ej. paneles solares, calentadores, bombas de agua, iluminación...)"
        new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
        return {"messages": new_messages, "contexto_tecnico": ctx}

    # ========================================================================
    # NODO GENERAR RESPUESTA (DINÁMICO Y CONTEXTUAL)
    # ========================================================================
    @auditar_fase(nombre_fase="Generación de Respuesta Comercial", criticidad="ALTA")
    @observe_node(node_name="generar_respuesta_comercial")
    async def generar_respuesta_comercial_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # --- 1. Extraer nombre/whatsapp (respaldo) ---
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
                prompt_text = get_prompt("jarvi_extractor_contacto", mensaje=ultimo_mensaje)
                extraccion = await extractor_llm.ainvoke(prompt_text)
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

        # --- 2. Obtener productos relevantes (si no existen) ---
        if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
            ctx["productos_interes"] = obtener_productos_relevantes(
                topologia=ctx["topologia"],
                tipo=ctx["tipo_producto"],
                max_items=5
            )

        # --- 3. Actualizar checklist con los datos extraídos ---
        checklist = ctx.get("checklist", {})
        if ctx.get("requisitos"):
            for req in ctx["requisitos"]:
                field = req.get("field")
                if field and ctx.get(field) is not None:
                    checklist[field] = "completado"
                elif field:
                    checklist[field] = "pendiente"
            ctx["checklist"] = checklist

        # --- 4. Construir regla_datos dinámica desde la checklist ---
        regla_datos = ""
        pendientes = []
        if checklist:
            for field, status in checklist.items():
                if status == "pendiente":
                    pregunta = "información adicional"
                    for req in ctx.get("requisitos", []):
                        if req.get("field") == field:
                            pregunta = req.get("question", field)
                            break
                    pendientes.append(pregunta)
            if pendientes:
                regla_datos = f"1. DEBES recopilar sutilmente las siguientes necesidades: {', '.join(pendientes)}."
            else:
                regla_datos = "Ya tienes toda la información técnica. Enfócate en ofrecer una solución y cerrar la conversación."
        else:
            # Fallback a la lógica original (si no hay checklist)
            if ctx.get("requiere_auditoria_electrica"):
                regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación, Consumo y Necesidad exacta."
            else:
                regla_datos = "1. DEBES recopilar sutilmente: Nombre, Ubicación y Necesidad exacta."

        # --- 5. Obtener ontología dinámica (fragmento) ---
        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))

        # --- 6. Normalizar contacto para metadata ---
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

        # --- 7. Construir conocimiento_usuario (para evitar redundancias) ---
        conocimiento_usuario = ""
        if ctx.get("nombre") and ctx.get("nombre") != "Usuario":
            conocimiento_usuario += f"El usuario se llama {ctx['nombre']}. "
        if ctx.get("ciudad"):
            conocimiento_usuario += f"Vive en {ctx['ciudad']}. "
        if ctx.get("consumo_mensual_kwh"):
            conocimiento_usuario += f"Consume {ctx['consumo_mensual_kwh']} kWh al mes. "
        if ctx.get("numero_personas"):
            conocimiento_usuario += f"Necesita agua caliente para {ctx['numero_personas']} personas. "
        if ctx.get("product_tag"):
            # Añadir información del producto detectado
            ontologia = cargar_ontologia()
            item = ontologia.get(ctx["product_tag"], {})
            if item.get("nombre"):
                conocimiento_usuario += f"Está interesado en {item['nombre']}. "

        if not conocimiento_usuario:
            conocimiento_usuario = "No se tiene información previa del usuario."

        # --- 8. Compilar y ejecutar el prompt del sistema ---
        prompt_content = get_prompt(
            "jarvi_system_prompt",
            ciudad=ctx.get('ciudad', 'PENDIENTE'),
            empresa_electrica=ctx.get('empresa_electrica', 'PENDIENTE'),
            tarifa_base_gtq=ctx.get('tarifa_base_gtq', 'PENDIENTE'),
            regla_datos=regla_datos,
            ontologia_dinamica=ontologia_dinamica,
            conocimiento_usuario=conocimiento_usuario   # <-- NUEVO PARÁMETRO
        )
        prompt_sistema = SystemMessage(content=prompt_content)

        # Uso del LLM con el cliente configurado
        respuesta = await llm.ainvoke([prompt_sistema] + state["messages"], config=config)
        return {"messages": [respuesta], "contexto_tecnico": ctx}

    @observe_node(node_name="anexar_caso_respuesta")
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
    # ENSAMBLAJE DEL GRAFO (SIN CAMBIOS)
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
