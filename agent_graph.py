"""
agent_graph.py - Grafo agéntico de JARVI 2.0 con instrumentación CTFOM.
VERSIÓN 2.1.0 – Checklist Universal, Cierre SMART, Diagnóstico Ontológico y Cálculo Off‑Grid 30JUL2026.
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

# Sanitización
from utils.sanitize import sanitize_pii

import config
from audit import auditar_fase
from ontology import (
    obtener_fragmento_ontologia,
    cargar_ontologia,
    obtener_productos_relevantes,
    inferir_tag_por_mensaje,
    get_requirements_by_tag,
    get_requires_diagnostic,          # Nueva función
    get_dimensionamiento_by_tag,      # Nueva función
    get_precio_by_tag                 # Nueva función (extrae precio desde la URL)
)
from telemetry import trace_id_var, span_id_var, schedule_telemetry_event
from ubicacion import buscar_ubicacion
from prompt_manager import get_prompt
from price_extractor import extract_price_from_url  # Nuevo módulo

logger = logging.getLogger(__name__)
from config import settings

# =============================================================================
# CONFIGURACIÓN DE API KEY (CON ROTACIÓN)
# =============================================================================
def get_llm():
    return ChatOpenAI(
        openai_api_key=settings.openai_api_key,
        model="gpt-4o-mini",
        temperature=0.1,
        timeout=60.0,
        max_retries=5,
        default_headers={"User-Agent": "JARVI/2.1.0"}
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
    # Nuevos campos para requisitos dinámicos y cierre
    product_tag: Optional[str]
    requisitos: Optional[List[Dict]]
    checklist_universal: Optional[Dict]      # Estado de los 13 campos
    fecha_estimada_compra: Optional[str]
    score_actual: Optional[float]

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
    """Inicializa la checklist con los 13 campos del scoring, marcando como completados los que ya están en ctx."""
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
    """Calcula el score basado en la checklist universal."""
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
    nombre_norm, whatsapp_norm = normalizar_contacto(nombre_apellidos, numero_whatsapp, departamento_municipio)
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
        await asyncio.to_thread(requests.post, endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
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
# CONSTRUCCIÓN DEL GRAFO
# =============================================================================
def create_graph(checkpointer: BaseCheckpointSaver):
    graph_builder = StateGraph(AgentState)
    llm = get_llm().bind_tools([procesar_oportunidad_backend])
    extractor_llm = llm.with_structured_output(ExtractorContacto)

    # --------------------------------------------------------------------------
    # NODO: CLASIFICADOR DE INTENCIÓN (sin asignación de diagnóstico)
    # --------------------------------------------------------------------------
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
                # No se asigna requiere_auditoria_electrica aquí; se hará en seleccionar_productos
            elif any(k in ultimo for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
                ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
        return {"contexto_tecnico": ctx}

    # --------------------------------------------------------------------------
    # NODO: VALIDADOR DE UBICACIÓN (SIN CAMBIOS)
    # --------------------------------------------------------------------------
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

    # --------------------------------------------------------------------------
    # NODO: SELECCIÓN DE PRODUCTOS (NUEVA LÓGICA ONTOLÓGICA)
    # --------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Selección de Productos", criticidad="ALTA")
    @observe_node(node_name="seleccionar_productos")
    async def seleccionar_productos_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))

        # Si ya tenemos tag, no volvemos a preguntar
        if ctx.get("product_tag"):
            return {"contexto_tecnico": ctx}

        # Intentar inferir producto del mensaje
        tag = inferir_tag_por_mensaje(ultimo)
        if tag:
            ctx["product_tag"] = tag
            # Cargar requisitos del producto
            requisitos = get_requirements_by_tag(tag)
            ctx["requisitos"] = requisitos
            # Leer flag de diagnóstico desde la ontología
            requires_diagnostic = get_requires_diagnostic(tag)
            ctx["requiere_auditoria_electrica"] = requires_diagnostic
            # Inicializar checklist universal (si no existe)
            if not ctx.get("checklist_universal"):
                ctx["checklist_universal"] = inicializar_checklist_universal(ctx)
            # Actualizar checklist con requisitos específicos
            checklist = ctx["checklist_universal"]
            for req in requisitos:
                field = req.get("field")
                if field and ctx.get(field) is not None:
                    checklist[field] = "completado"
                elif field:
                    checklist[field] = "pendiente"
            ctx["checklist_universal"] = checklist
            logger.info(f"Producto detectado: tag={tag}, requisitos={len(requisitos)}")
            return {"contexto_tecnico": ctx}

        # Si no se infiere producto, preguntar al usuario
        pregunta = "¿Sobre qué tipo de equipo le gustaría recibir asesoría? (ej. paneles solares, calentadores, bombas de agua, iluminación...)"
        new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
        return {"messages": new_messages, "contexto_tecnico": ctx}

    # --------------------------------------------------------------------------
    # NODO: CÁLCULO DE CARGA OFF‑GRID (NUEVO)
    # --------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Cálculo de Carga Off‑Grid", criticidad="ALTA")
    @observe_node(node_name="calcular_carga_offgrid")
    async def calcular_carga_offgrid_node(state: AgentState):
        ctx = dict(state.get("contexto_tecnico") or {})
        ultimo = extraer_intencion_humana(state.get("messages", []))

        # Verificar si es Off‑Grid y aún no se ha calculado la carga
        topologia = ctx.get("topologia", "")
        if "OFF-GRID" not in topologia.upper():
            return {"contexto_tecnico": ctx}
        if ctx.get("calculo_carga_completado"):
            return {"contexto_tecnico": ctx}

        # Obtener datos de dimensionamiento desde la ontología
        tag = ctx.get("product_tag")
        if not tag:
            return {"contexto_tecnico": ctx}
        dimensionamiento = get_dimensionamiento_by_tag(tag)
        if not dimensionamiento:
            logger.warning(f"No hay dimensionamiento para tag {tag}")
            return {"contexto_tecnico": ctx}

        equipos_tipicos = dimensionamiento.get("equipos_tipicos", [])
        # Si el mensaje contiene números y palabras clave, intentar extraer equipos
        # Por simplicidad, aquí se pregunta al usuario si no se ha hecho antes
        # Se puede implementar una lógica de extracción, pero por ahora preguntamos
        if not ctx.get("equipos_usuario"):
            pregunta = "Para dimensionar su sistema Off‑Grid, ¿qué equipos planea usar y cuántas horas al día? (ej. 'Nevera 24h, TV 6h, bombillas 8h')"
            new_messages = state.get("messages", []) + [AIMessage(content=pregunta)]
            return {"messages": new_messages, "contexto_tecnico": ctx}

        # Si ya hay respuesta, procesar el cálculo (esto se haría en otro nodo o en el mismo)
        # Por ahora, solo marcamos como completado si ya hay equipos
        # La lógica completa se puede implementar en un nodo posterior.
        return {"contexto_tecnico": ctx}

    # --------------------------------------------------------------------------
    # NODO: GENERAR RESPUESTA (DINÁMICO Y CONTEXTUAL)
    # --------------------------------------------------------------------------
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

        # --- 3. Asegurar que existe checklist universal ---
        if not ctx.get("checklist_universal"):
            ctx["checklist_universal"] = inicializar_checklist_universal(ctx)
        checklist = ctx["checklist_universal"]

        # --- 4. Actualizar checklist con datos extraídos ---
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

        # --- 5. Calcular score ---
        score = calcular_puntaje_completitud(ctx)
        ctx["score_actual"] = score
        logger.info(f"Score actual: {score}%")

        # --- 6. Construir regla_datos desde la checklist ---
        pendientes = [campo for campo, status in checklist.items() if status == "pendiente"]
        if pendientes:
            # Priorizar preguntas: primero topologia, luego tipo_producto, luego productos_interes, luego el resto
            prioridad = ["topologia", "tipo_producto", "productos_interes", "departamento", "municipio", "ciudad",
                         "empresa_electrica", "tarifa_base_gtq", "consumo_mensual_kwh", "vendedor"]
            # Ordenar pendientes según prioridad
            pendientes_ordenados = sorted(pendientes, key=lambda x: prioridad.index(x) if x in prioridad else 99)
            preguntas = []
            for campo in pendientes_ordenados:
                # Buscar pregunta asociada en requisitos (si existe)
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

        # --- 7. Obtener ontología dinámica ---
        ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))

        # --- 8. Normalizar contacto para metadata ---
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

        # --- 9. Construir conocimiento_usuario ---
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

        # --- 10. Compilar y ejecutar el prompt del sistema ---
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

    # --------------------------------------------------------------------------
    # NODO: VERIFICAR CIERRE (NUEVO)
    # --------------------------------------------------------------------------
    @auditar_fase(nombre_fase="Verificación de Cierre Comercial", criticidad="ALTA")
    @observe_node(node_name="verificar_cierre")
    async def verificar_cierre_node(state: AgentState, config: RunnableConfig):
        ctx = dict(state.get("contexto_tecnico") or {})
        score = ctx.get("score_actual", 0.0)
        messages = state.get("messages", [])

        # Si el score es menor a 60%, no activar cierre
        if score < 60.0:
            return {}

        # Verificar si ya se hizo el cierre (para no repetir)
        if ctx.get("cierre_realizado"):
            return {}

        # Obtener precio del producto (desde la URL)
        precio_texto = ""
        tag = ctx.get("product_tag")
        if tag:
            try:
                precio_data = get_precio_by_tag(tag)
                if precio_data and precio_data.get("precio"):
                    precio = precio_data["precio"]
                    moneda = precio_data.get("moneda", "GTQ")
                    precio_texto = f"**{precio:,.2f} {moneda}**"
                else:
                    precio_texto = "disponible bajo consulta"
            except Exception as e:
                logger.error(f"Error al obtener precio para tag {tag}: {e}")
                precio_texto = "disponible bajo consulta"

        # Construir mensaje de cierre
        nombre_producto = ""
        if tag:
            ontologia = cargar_ontologia()
            item = ontologia.get(tag, {})
            nombre_producto = item.get("nombre", "el producto")

        # Resumen de la solución
        resumen = f"Resumen de su solución: {nombre_producto} con un costo aproximado de {precio_texto}."
        advertencia = "Le recuerdo que este precio no incluye instalación, mano de obra, servicios adicionales ni costos de envío."

        # Preguntas de cierre
        preguntas = [
            f"{resumen} {advertencia}",
            "¿Cómo visualiza esta solución para su caso?",
            "Para poder coordinar la entrega e instalación, ¿qué fecha estimada le gustaría tener el equipo operativo?",
            "Actualmente, ¿tiene un vendedor asignado? Si no es así, ¿le gustaría que uno de nuestro equipo lo contacte?"
        ]

        # Añadir preguntas al historial de mensajes
        for pregunta in preguntas:
            messages.append(AIMessage(content=pregunta))

        # Marcar cierre como realizado
        ctx["cierre_realizado"] = True
        return {"messages": messages, "contexto_tecnico": ctx}

    # --------------------------------------------------------------------------
    # NODO: ANEXAR CASO (SIN CAMBIOS)
    # --------------------------------------------------------------------------
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
    # ENSAMBLAJE DEL GRAFO
    # =========================================================================
    graph_builder.add_node("clasificar_intencion_comercial", clasificar_intencion_comercial_node)
    graph_builder.add_node("validar_ubicacion_cliente", validar_ubicacion_cliente_node)
    graph_builder.add_node("seleccionar_productos", seleccionar_productos_node)
    graph_builder.add_node("calcular_carga_offgrid", calcular_carga_offgrid_node)
    graph_builder.add_node("generar_respuesta_comercial", generar_respuesta_comercial_node)
    graph_builder.add_node("verificar_cierre", verificar_cierre_node)
    graph_builder.add_node("anexar_caso_respuesta", anexar_caso_respuesta_node)
    graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))

    def my_tools_condition(state: AgentState):
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return "tools"
        return "verificar_cierre"  # Cambio: después de generar respuesta, verificar cierre

    graph_builder.add_edge(START, "clasificar_intencion_comercial")
    graph_builder.add_edge("clasificar_intencion_comercial", "validar_ubicacion_cliente")
    graph_builder.add_edge("validar_ubicacion_cliente", "seleccionar_productos")
    graph_builder.add_edge("seleccionar_productos", "calcular_carga_offgrid")
    graph_builder.add_edge("calcular_carga_offgrid", "generar_respuesta_comercial")
    graph_builder.add_conditional_edges("generar_respuesta_comercial", my_tools_condition)
    graph_builder.add_edge("tools", "anexar_caso_respuesta")
    graph_builder.add_edge("verificar_cierre", "anexar_caso_respuesta")
    graph_builder.add_edge("anexar_caso_respuesta", END)

    return graph_builder.compile(checkpointer=checkpointer)

if __name__ == "__main__":
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer_studio = MemorySaver()
    jarvi_graph = create_graph(checkpointer_studio)
else:
    jarvi_graph = None
