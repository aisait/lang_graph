"""
agent_graph.py - Grafo agéntico de JARVI 2.0 con instrumentación CTFOM.
VERSIÓN 2.3.0 – Extracción semántica de checklist, precios dinámicos, sin # ni *.
30JUL2026.
"""
import os
import time
import uuid
import asyncio
import requests
import re
import functools
import logging
from typing import Annotated, TypedDict, Optional, List, Dict, Any
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver

from utils.sanitize import sanitize_pii
import config
from audit import auditar_fase
from ontology import (
    obtener_fragmento_ontologia,
    cargar_ontologia,
    obtener_productos_relevantes,
    inferir_tag_por_mensaje,
    get_requirements_by_tag,
    get_requires_diagnostic,
    get_dimensionamiento_by_tag,
    get_precio_by_tag
)
from telemetry import trace_id_var, span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion
from prompt_manager import get_prompt

logger = logging.getLogger(__name__)
from config import settings

# =============================================================================
# CONFIGURACIÓN DE API KEY
# =============================================================================
def get_llm():
    return ChatOpenAI(
        openai_api_key=settings.openai_api_key,
        model="gpt-4o-mini",
        temperature=0.1,
        timeout=60.0,
        max_retries=5,
        default_headers={"User-Agent": "JARVI/2.3.0"}
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
# ESQUEMAS
# =============================================================================
class ExtractorContacto(BaseModel):
    nombre: Optional[str] = Field(None, description="Nombre de pila y apellidos.")
    telefono: Optional[str] = Field(None, description="Número telefónico.")

class ChecklistExtract(BaseModel):
    """Esquema para extracción semántica de los 13 campos del scoring."""
    nombre: Optional[str] = Field(None, description="Nombre completo del cliente.")
    whatsapp: Optional[str] = Field(None, description="Número de teléfono en formato E.164.")
    departamento: Optional[str] = Field(None, description="Departamento de Guatemala.")
    municipio: Optional[str] = Field(None, description="Municipio de Guatemala.")
    ciudad: Optional[str] = Field(None, description="Ciudad o localidad.")
    empresa_electrica: Optional[str] = Field(None, description="Empresa distribuidora de electricidad (EEGSA, DEOCSA, etc.).")
    tarifa_base_gtq: Optional[float] = Field(None, description="Tarifa eléctrica en GTQ por kWh.")
    topologia: Optional[str] = Field(None, description="On-Grid, Off-Grid, o No aplica.")
    calculo_carga_completado: Optional[bool] = Field(None, description="Si ya se calculó la carga eléctrica.")
    requiere_auditoria_electrica: Optional[bool] = Field(None, description="Si el producto requiere diagnóstico eléctrico.")
    vendedor: Optional[str] = Field(None, description="Nombre del vendedor asignado.")
    tipo_producto: Optional[str] = Field(None, description="sistema o unitario.")
    productos_interes: Optional[List[str]] = Field(None, description="Lista de nombres de productos de interés.")

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
    product_tag: Optional[str]
    requisitos: Optional[List[Dict]]
    checklist_universal: Optional[Dict]
    fecha_estimada_compra: Optional[str]
    score_actual: Optional[float]
    cierre_realizado: Optional[bool]
    iteraciones_sin_cambio: Optional[int]

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica

# =============================================================================
# FUNCIONES AUXILIARES PARA CHECKLIST Y SCORING
# =============================================================================
CAMPOS_SCORE_UNIVERSAL = [
    "nombre", "whatsapp", "departamento", "municipio", "ciudad",
    "empresa_electrica", "tarifa_base_gtq", "topologia",
    "calculo_carga_completado", "requiere_auditoria_electrica",
    "vendedor", "tipo_producto", "productos_interes"
]

def inicializar_checklist_universal(ctx: dict) -> dict:
    checklist = {}
    for campo in CAMPOS_SCORE_UNIVERSAL:
        valor = ctx.get(campo)
        if campo == "productos_interes" and isinstance(valor, list) and valor:
            checklist[campo] = "completado"
        elif campo == "tipo_producto" and valor:
            checklist[campo] = "completado"
        elif campo == "vendedor" and valor:
            checklist[campo] = "completado"
        elif campo == "calculo_carga_completado" and valor:
            checklist[campo] = "completado"
        elif campo == "requiere_auditoria_electrica" and valor is not None:
            checklist[campo] = "completado"
        elif isinstance(valor, str) and valor and valor != "Pendiente":
            checklist[campo] = "completado"
        elif isinstance(valor, float) and valor > 0:
            checklist[campo] = "completado"
        else:
            checklist[campo] = "pendiente"
    return checklist

def calcular_puntaje_completitud(ctx: dict) -> float:
    checklist = ctx.get("checklist_universal")
    if not checklist:
        checklist = inicializar_checklist_universal(ctx)
        ctx["checklist_universal"] = checklist
    completados = sum(1 for status in checklist.values() if status == "completado")
    return round((completados / len(CAMPOS_SCORE_UNIVERSAL)) * 100, 2)

# =============================================================================
# DECORADOR CTFOM
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
# HERRAMIENTA DE ENVÍO A N8N
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
    Envía los datos de una oportunidad de negocio al backend de n8n para su procesamiento.
    """
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
    endpoint = os.getenv("N8N_WEBHOOK_URL", "")
    if not endpoint:
        logger.warning("N8N_WEBHOOK_URL no configurado. Lead no enviado.")
        return "No se pudo enviar el lead: webhook no configurado."
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
        await asyncio.to_thread(requests.post, endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        logger.info(f"Lead enviado exitosamente a N8N para {whatsapp_norm}")
        return f"Lead enviado a N8N. Contacto: {whatsapp_norm}."
    except Exception as e:
        logger.error(f"Fallo en envío a N8N: {e}")
        return f"Error al enviar lead: {str(e)}"

# =============================================================================
# FUNCIONES AUXILIARES
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
    if not mensaje:
        return None
    mensaje_lower = mensaje.lower()
    patron_sistema = r'\b(sistema|kit|completo|llave en mano|instalación completa|pack solar|planta solar|proyecto llave en mano|integral)\b'
    patron_unitario = r'\b(producto|unitario|componente|inversor|panel|módulo|batería|acumulador|calentador|termo|bomba|controlador|cargador|estructura|soporte|cable|conector|regulador)\b'
    if re.search(patron_sistema, mensaje_lower):
        return "sistema"
    if re.search(patron_unitario, mensaje_lower):
        return "unitario"
    if re.search(r'\b(solar|fotovoltaico|fotovoltaica|energía solar)\b', mensaje_lower):
        return "unitario"
    return None

# =============================================================================
# CONSTRUCCIÓN DEL GRAFO
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = get_llm().bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)
    checklist_llm = llm.with_structured_output(ChecklistExtract)

    # -------------------------------------------------------------------------
    # NODO 1: CLASIFICADOR DE INTENCIÓN (SOLO DETECCIÓN EXPLÍCITA)
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Clasificador de Intención Comercial", criticidad="MEDIA")
    @observe_node(node_name="clasificar_intencion_comercial")
    async def clasificar_intencion_comercial_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))
        if not ultimo:
            return {"contexto_tecnico": ctx}
        if ctx.get("topologia"):
            return {"contexto_tecnico": ctx}
        if re.search(r'\b(on\s*grid|conectado a la red|atado a la red|sistema de red)\b', ultimo, re.IGNORECASE):
            ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
            logger.info(f"Topología On-Grid detectada explícitamente.")
        elif re.search(r'\b(off\s*grid|aislado|sin red|autónomo|independiente)\b', ultimo, re.IGNORECASE):
            ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
            logger.info(f"Topología Off-Grid detectada explícitamente.")
        return {"contexto_tecnico": ctx}

    # -------------------------------------------------------------------------
    # NODO 2: VALIDADOR DE UBICACIÓN
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # NODO 3: SELECCIÓN DE PRODUCTOS (PRIORIDAD ONTOLÓGICA)
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Selección de Productos", criticidad="ALTA")
    @observe_node(node_name="seleccionar_productos")
    async def seleccionar_productos_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))

        if ctx.get("product_tag"):
            return {"contexto_tecnico": ctx}

        tag = inferir_tag_por_mensaje(ultimo)
        if tag:
            ctx["product_tag"] = tag
            logger.info(f"Producto detectado: tag={tag}")
            ontologia = cargar_ontologia()
            item = ontologia.get(tag, {})
            tipo_producto = item.get("tipo", "unitario")
            requisitos = get_requirements_by_tag(tag)
            ctx["requisitos"] = requisitos
            requires_diagnostic = get_requires_diagnostic(tag)
            ctx["requiere_auditoria_electrica"] = requires_diagnostic

            if tipo_producto == "sistema":
                tag_int = int(tag) if tag.isdigit() else 0
                ongrid_tags = list(range(1, 11)) + [20, 35, 37, 38, 60, 61, 64, 79, 80, 81, 85]
                offgrid_tags = [19, 50, 51, 52, 53, 56, 57, 58, 59, 62, 66, 69, 70, 71]
                if tag_int in ongrid_tags:
                    ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
                    ctx["tipo_producto"] = "sistema"
                elif tag_int in offgrid_tags:
                    ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
                    ctx["tipo_producto"] = "sistema"
                else:
                    ctx["topologia"] = "Pendiente (sistema no clasificado)"
            else:
                ctx["topologia"] = "No aplica (Producto unitario)"
                ctx["tipo_producto"] = "unitario"

            if not ctx.get("checklist_universal"):
                ctx["checklist_universal"] = inicializar_checklist_universal(ctx)
            checklist = ctx["checklist_universal"]
            if ctx.get("topologia") and "Pendiente" not in ctx["topologia"]:
                checklist["topologia"] = "completado"
            if ctx.get("tipo_producto"):
                checklist["tipo_producto"] = "completado"
            for req in requisitos:
                field = req.get("field")
                if field and ctx.get(field) is not None:
                    checklist[field] = "completado"
                elif field:
                    checklist[field] = "pendiente"
            ctx["checklist_universal"] = checklist
            return {"contexto_tecnico": ctx}

        pregunta = "¿Sobre qué tipo de equipo le gustaría recibir asesoría? (ej. paneles solares, calentadores, bombas de agua, iluminación...)"
        new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
        return {"messages": new_messages, "contexto_tecnico": ctx}

    # -------------------------------------------------------------------------
    # NODO 4: CÁLCULO DE CARGA OFF-GRID
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Cálculo de Carga Off‑Grid", criticidad="ALTA")
    @observe_node(node_name="calcular_carga_offgrid")
    async def calcular_carga_offgrid_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        topologia = ctx.get("topologia", "")
        if "OFF-GRID" not in topologia.upper():
            return {"contexto_tecnico": ctx}
        if ctx.get("calculo_carga_completado"):
            return {"contexto_tecnico": ctx}
        tag = ctx.get("product_tag")
        if not tag:
            return {"contexto_tecnico": ctx}
        dimensionamiento = get_dimensionamiento_by_tag(tag)
        if not dimensionamiento:
            return {"contexto_tecnico": ctx}
        if not ctx.get("equipos_usuario"):
            pregunta = "Para dimensionar su sistema Off‑Grid, ¿qué equipos planea usar y cuántas horas al día? (ej. Nevera 24h, TV 6h, bombillas 8h)"
            new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
            return {"messages": new_messages, "contexto_tecnico": ctx}
        return {"contexto_tecnico": ctx}

    # -------------------------------------------------------------------------
    # NODO 5: GENERAR RESPUESTA COMERCIAL
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Generación de Respuesta Comercial", criticidad="ALTA")
    @observe_node(node_name="generar_respuesta_comercial")
    async def generar_respuesta_comercial_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo_mensaje = extraer_intencion_humana(state.get("messages", []))

        # Extracción básica por regex (fallback)
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

        if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
            ctx["productos_interes"] = obtener_productos_relevantes(
                topologia=ctx["topologia"],
                tipo=ctx["tipo_producto"],
                max_items=5
            )

        if not ctx.get("checklist_universal"):
            ctx["checklist_universal"] = inicializar_checklist_universal(ctx)
        checklist = ctx["checklist_universal"]

        for campo in CAMPOS_SCORE_UNIVERSAL:
            valor = ctx.get(campo)
            if campo == "productos_interes" and isinstance(valor, list) and valor:
                checklist[campo] = "completado"
            elif campo == "tipo_producto" and valor:
                checklist[campo] = "completado"
            elif campo == "vendedor" and valor:
                checklist[campo] = "completado"
            elif campo == "calculo_carga_completado" and valor:
                checklist[campo] = "completado"
            elif campo == "requiere_auditoria_electrica" and valor is not None:
                checklist[campo] = "completado"
            elif isinstance(valor, str) and valor and valor != "Pendiente":
                checklist[campo] = "completado"
            elif isinstance(valor, float) and valor > 0:
                checklist[campo] = "completado"
            elif checklist.get(campo) != "completado":
                checklist[campo] = "pendiente"
        ctx["checklist_universal"] = checklist

        score = calcular_puntaje_completitud(ctx)
        ctx["score_actual"] = score
        logger.info(f"Score actual: {score}%")

        pendientes = [campo for campo, status in checklist.items() if status == "pendiente"]
        if pendientes:
            prioridad = ["topologia", "tipo_producto", "productos_interes", "departamento", "municipio", "ciudad",
                         "empresa_electrica", "tarifa_base_gtq", "consumo_mensual_kwh", "vendedor"]
            pendientes_ordenados = sorted(pendientes, key=lambda x: prioridad.index(x) if x in prioridad else 99)
            preguntas = []
            for campo in pendientes_ordenados:
                pregunta = f"¿Cuál es su {campo.replace('_',' ')}?"
                if ctx.get("requisitos"):
                    for req in ctx.get("requisitos", []):
                        if req.get("field") == campo:
                            pregunta = req.get("question", pregunta)
                            break
                preguntas.append(pregunta)
            regla_datos = f"1. DEBES recopilar sutilmente: {', '.join(preguntas)}."
        else:
            regla_datos = "Ya tienes toda la información técnica. Enfócate en ofrecer una solución y cerrar la conversación."

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
            ontologia = cargar_ontologia()
            item = ontologia.get(ctx["product_tag"], {})
            if item.get("nombre"):
                conocimiento_usuario += f"Está interesado en {item['nombre']}. "
        if ctx.get("productos_interes"):
            nombres = [p.get("nombre") for p in ctx["productos_interes"] if p.get("nombre")]
            if nombres:
                conocimiento_usuario += f"Productos de interés: {', '.join(nombres)}. "
        if not conocimiento_usuario:
            conocimiento_usuario = "No se tiene información previa del usuario."

        prompt_content = get_prompt(
            "jarvi_system_prompt",
            ciudad=ctx.get('ciudad', 'PENDIENTE'),
            empresa_electrica=ctx.get('empresa_electrica', 'PENDIENTE'),
            tarifa_base_gtq=ctx.get('tarifa_base_gtq', 'PENDIENTE'),
            regla_datos=regla_datos,
            ontologia_dinamica=ontologia_dinamica,
            conocimiento_usuario=conocimiento_usuario
        )
        prompt_sistema = SystemMessage(content=prompt_content)

        respuesta = await llm.ainvoke([prompt_sistema] + state["messages"], config=config)
        return {"messages": [respuesta], "contexto_tecnico": ctx}

    # -------------------------------------------------------------------------
    # NODO 6: ACTUALIZAR CHECKLIST (EXTRACCIÓN SEMÁNTICA CON LLM)
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Actualización Semántica de Checklist", criticidad="ALTA")
    @observe_node(node_name="actualizar_checklist")
    async def actualizar_checklist_node(state: AgentState):
        """
        Nodo que utiliza el LLM para extraer los 13 campos del scoring
        de todo el historial de conversación. Esto desbloquea el scoring
        al interpretar semánticamente las respuestas del usuario.
        """
        ctx = dict(state.get("contexto_tecnico") or {})
        messages = state.get("messages", [])

        # Construir el historial completo como texto
        historial_texto = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                historial_texto += f"Usuario: {msg.content}\n"
            elif isinstance(msg, AIMessage):
                historial_texto += f"Asistente: {msg.content}\n"

        if not historial_texto:
            return {"contexto_tecnico": ctx}

        # Si ya tenemos un tag, lo usamos para mejorar la extracción
        tag_info = ""
        if ctx.get("product_tag"):
            ontologia = cargar_ontologia()
            item = ontologia.get(ctx["product_tag"], {})
            tag_info = f"Producto detectado: {item.get('nombre', '')} (tag {ctx['product_tag']})"

        prompt_extract = f"""
        Extrae los siguientes campos de la conversación. Si no se mencionan, déjalos como null.
        Usa solo la información explícitamente mencionada por el usuario.
        No inventes datos.

        {tag_info}

        Historial de la conversación:
        {historial_texto}

        Campos a extraer:
        - nombre: Nombre completo del cliente.
        - whatsapp: Número de teléfono (formato E.164, ej. +50212345678).
        - departamento: Departamento de Guatemala.
        - municipio: Municipio de Guatemala.
        - ciudad: Ciudad o localidad.
        - empresa_electrica: Empresa distribuidora (EEGSA, DEOCSA, etc.).
        - tarifa_base_gtq: Tarifa eléctrica en GTQ/kWh (número).
        - topologia: On-Grid, Off-Grid, o No aplica.
        - calculo_carga_completado: true/false.
        - requiere_auditoria_electrica: true/false.
        - vendedor: Nombre del vendedor asignado.
        - tipo_producto: sistema o unitario.
        - productos_interes: Lista de nombres de productos mencionados.
        """

        try:
            extraccion: ChecklistExtract = await checklist_llm.ainvoke(prompt_extract)
        except Exception as e:
            logger.error(f"Error en extracción semántica: {e}")
            return {"contexto_tecnico": ctx}

        # Actualizar ctx con los valores extraídos (solo si no están ya seteados)
        if extraccion.nombre and not ctx.get("nombre"):
            ctx["nombre"] = extraccion.nombre
        if extraccion.whatsapp and not ctx.get("whatsapp"):
            ctx["whatsapp"] = extraccion.whatsapp
        if extraccion.departamento and not ctx.get("departamento"):
            ctx["departamento"] = extraccion.departamento
        if extraccion.municipio and not ctx.get("municipio"):
            ctx["municipio"] = extraccion.municipio
        if extraccion.ciudad and not ctx.get("ciudad"):
            ctx["ciudad"] = extraccion.ciudad
        if extraccion.empresa_electrica and not ctx.get("empresa_electrica"):
            ctx["empresa_electrica"] = extraccion.empresa_electrica
        if extraccion.tarifa_base_gtq and not ctx.get("tarifa_base_gtq"):
            ctx["tarifa_base_gtq"] = extraccion.tarifa_base_gtq
        if extraccion.topologia and not ctx.get("topologia"):
            ctx["topologia"] = extraccion.topologia
        if extraccion.calculo_carga_completado is not None and not ctx.get("calculo_carga_completado"):
            ctx["calculo_carga_completado"] = extraccion.calculo_carga_completado
        if extraccion.requiere_auditoria_electrica is not None and not ctx.get("requiere_auditoria_electrica"):
            ctx["requiere_auditoria_electrica"] = extraccion.requiere_auditoria_electrica
        if extraccion.vendedor and not ctx.get("vendedor"):
            ctx["vendedor"] = extraccion.vendedor
        if extraccion.tipo_producto and not ctx.get("tipo_producto"):
            ctx["tipo_producto"] = extraccion.tipo_producto
        if extraccion.productos_interes and not ctx.get("productos_interes"):
            ctx["productos_interes"] = extraccion.productos_interes

        # Actualizar checklist
        if not ctx.get("checklist_universal"):
            ctx["checklist_universal"] = inicializar_checklist_universal(ctx)
        checklist = ctx["checklist_universal"]

        for campo in CAMPOS_SCORE_UNIVERSAL:
            valor = ctx.get(campo)
            if campo == "productos_interes" and isinstance(valor, list) and valor:
                checklist[campo] = "completado"
            elif campo == "tipo_producto" and valor:
                checklist[campo] = "completado"
            elif campo == "vendedor" and valor:
                checklist[campo] = "completado"
            elif campo == "calculo_carga_completado" and valor:
                checklist[campo] = "completado"
            elif campo == "requiere_auditoria_electrica" and valor is not None:
                checklist[campo] = "completado"
            elif isinstance(valor, str) and valor and valor != "Pendiente":
                checklist[campo] = "completado"
            elif isinstance(valor, float) and valor > 0:
                checklist[campo] = "completado"
            elif checklist.get(campo) != "completado":
                checklist[campo] = "pendiente"

        ctx["checklist_universal"] = checklist
        score = calcular_puntaje_completitud(ctx)
        ctx["score_actual"] = score
        logger.info(f"Score tras extracción semántica: {score}%")

        return {"contexto_tecnico": ctx}

    # -------------------------------------------------------------------------
    # NODO 7: VERIFICAR CIERRE (VERSIÓN DEFINITIVA – SIN # NI *)
    # -------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Verificación de Cierre Comercial", criticidad="ALTA")
    @observe_node(node_name="verificar_cierre")
    async def verificar_cierre_node(state: AgentState, config: RunnableConfig):
        """
        Nodo que evalúa el score y, si es >= 60%, activa el cierre SMART.
        Usa get_precio_by_tag para obtener el precio exacto desde la URL del producto.
        """
        ctx = dict(state.get("contexto_tecnico") or {})
        score = ctx.get("score_actual", 0.0)
        messages = state.get("messages", [])

        if score < 60.0:
            logger.debug(f"Score {score} < 60, no se activa cierre.")
            return {"contexto_tecnico": ctx}

        if ctx.get("cierre_realizado"):
            logger.debug("Cierre ya realizado, omitiendo.")
            return {"contexto_tecnico": ctx}

        # Obtener precio exacto desde la URL
        precio_texto = ""
        tag = ctx.get("product_tag")
        if tag:
            try:
                precio_data = get_precio_by_tag(tag)
                if precio_data and precio_data.get("precio"):
                    precio = precio_data["precio"]
                    moneda = precio_data.get("moneda", "GTQ")
                    precio_texto = f"{precio:,.2f} {moneda}"
                else:
                    precio_texto = "disponible bajo consulta"
            except Exception as e:
                logger.error(f"Error al obtener precio para tag {tag}: {e}")
                precio_texto = "disponible bajo consulta"
        else:
            precio_texto = "disponible bajo consulta"

        nombre_producto = ""
        if tag:
            ontologia = cargar_ontologia()
            item = ontologia.get(tag, {})
            nombre_producto = item.get("nombre", "el producto")

        resumen = f"Resumen de su solución: {nombre_producto} con un costo aproximado de {precio_texto}."
        advertencia = "Le recuerdo que este precio no incluye instalación, mano de obra, servicios adicionales ni costos de envío."

        preguntas = [
            f"{resumen} {advertencia}",
            "¿Cómo visualiza esta solución para su caso?",
            "Para poder coordinar la entrega e instalación, ¿qué fecha estimada le gustaría tener el equipo operativo?",
            "Actualmente, ¿tiene un vendedor asignado? Si no es así, ¿le gustaría que uno de nuestro equipo lo contacte?"
        ]

        for pregunta in preguntas:
            messages.append(AIMessage(content=pregunta))

        ctx["cierre_realizado"] = True

        return {
            "messages": messages,
            "contexto_tecnico": ctx
        }

    # -------------------------------------------------------------------------
    # NODO 8: ANEXAR CASO
    # -------------------------------------------------------------------------
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
    # ENSAMBLAJE DEL GRAFO (CON NUEVO NODO actualizar_checklist)
    # =========================================================================
    graph_builder.add_node("clasificar_intencion_comercial", clasificar_intencion_comercial_node)
    graph_builder.add_node("validar_ubicacion_cliente", validar_ubicacion_cliente_node)
    graph_builder.add_node("seleccionar_productos", seleccionar_productos_node)
    graph_builder.add_node("calcular_carga_offgrid", calcular_carga_offgrid_node)
    graph_builder.add_node("generar_respuesta_comercial", generar_respuesta_comercial_node)
    graph_builder.add_node("actualizar_checklist", actualizar_checklist_node)  # NUEVO
    graph_builder.add_node("verificar_cierre", verificar_cierre_node)
    graph_builder.add_node("anexar_caso_respuesta", anexar_caso_respuesta_node)
    graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))

    def my_tools_condition(state: AgentState):
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "tools"
        return "actualizar_checklist"  # Cambio: ir a actualizar_checklist antes de cierre

    graph_builder.add_edge(START, "clasificar_intencion_comercial")
    graph_builder.add_edge("clasificar_intencion_comercial", "validar_ubicacion_cliente")
    graph_builder.add_edge("validar_ubicacion_cliente", "seleccionar_productos")
    graph_builder.add_edge("seleccionar_productos", "calcular_carga_offgrid")
    graph_builder.add_edge("calcular_carga_offgrid", "generar_respuesta_comercial")
    graph_builder.add_conditional_edges("generar_respuesta_comercial", my_tools_condition)
    graph_builder.add_edge("tools", "actualizar_checklist")
    graph_builder.add_edge("actualizar_checklist", "verificar_cierre")
    graph_builder.add_edge("verificar_cierre", "anexar_caso_respuesta")
    graph_builder.add_edge("anexar_caso_respuesta", END)

    return graph_builder.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer_studio = MemorySaver()
    jarvi_graph = create_graph(checkpointer_studio)
else:
    jarvi_graph = None
