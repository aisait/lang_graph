import streamlit as st
import os
import requests
import uuid
import io
import json
import smtplib
import traceback
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Annotated, TypedDict, Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# IMPORTACIÓN Y CLIENTE PARA OPENAI (Whisper + TTS)
from openai import OpenAI

# =====================================================================
# 1. DEFINICIÓN DEL ESTADO (ACTUALIZADO - RUTEO EPISTEMOLÓGICO)
# =====================================================================
class InferenciaEnergetica(TypedDict):
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool
    requiere_auditoria_electrica: bool # NUEVO: Control de adquisición de datos

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica  

# =====================================================================
# 2. CONFIGURACIÓN Y PERSISTENCIA
# =====================================================================
load_dotenv()

# Variables para API de Acruxlab / Odoo
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

@st.cache_resource
def get_memory():
    return MemorySaver()

memory = get_memory()

# =====================================================================
# 3. ONTOLOGÍA FRAGMENTADA (OPTIMIZACIÓN DE VENTANA DE CONTEXTO)
# =====================================================================
ONTOLOGIA_BLOQUES = {
    "PANELES": """ENERGÍA SOLAR (CAPTACIÓN FOTOVOLTAICA)
1 — https://www.aisa.com.gt/shop/category/paneles-solares-18 (panel solar, placa solar, módulo fotovoltaico)
2 — https://www.aisa.com.gt/shop/category/paneles-solares-monocristalinos-19 (monocristalino, mono panel, alta eficiencia)
3 — https://www.aisa.com.gt/shop/category/paneles-solares-policristalinos-20 (policristalino, poli panel, económico)
4 — https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7 (on-grid, interconectado, net metering)
5 — https://www.aisa.com.gt/shop/category/sistemas-aislados-17 (off-grid, aislado, solar rural)
6 — https://www.aisa.com.gt/shop/category/sistemas-hibridos-96 (híbrido, backup solar, inteligente)""",
    
    "INVERSORES": """CONVERSIÓN ENERGÉTICA (INVERSORES Y TRANSFORMADORES)
7 — https://www.aisa.com.gt/shop/category/inversores-22 (inverter, inversor, convertidor, caja solar)
8 — https://www.aisa.com.gt/shop/category/inversor-hibrido-67 (hybrid inverter, híbrido, backup)
9 — https://www.aisa.com.gt/shop/category/micro-inv-45 (microinverter, micro, optimizador)
10 — https://www.aisa.com.gt/shop/category/inversor-carga-23 (inversor cargador, combo, integrado)
11 — https://www.aisa.com.gt/shop/category/inversor-senoidal-pura-24 (senoidal, onda pura, calidad eléctrica)
12 — https://www.aisa.com.gt/shop/category/inversor-senoidal-modificada-25 (onda modificada, económico)""",

    "CONTROLADORES": """CONTROL Y GESTIÓN DE ENERGÍA
13 — https://www.aisa.com.gt/shop/category/controladores-15 (controlador, regulador, cargador)
14 — https://www.aisa.com.gt/shop/category/controlador-mppt-39 (MPPT, controlador avanzado)
15 — https://www.aisa.com.gt/shop/category/controlador-pwm-40 (PWM, controlador básico, económico)
16 — https://www.aisa.com.gt/shop/category/medidores-de-energia-42 (medidor, monitor, wattmeter)""",

    "BATERIAS": """ALMACENAMIENTO ENERGÉTICO
17 — https://www.aisa.com.gt/shop/category/baterias-solares-21 (batería solar, banco, acumulador)
18 — https://www.aisa.com.gt/shop/category/baterias-solares-bateria-de-gel-26 (gel battery, sellada, AGM)
19 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-backup-105 (backup battery, UPS)
20 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-litio-106 (li-ion, litio, alta performance)
21 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-estacionarias-27 (estacionaria, ciclo profundo)
22 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-arranque-28 (arranque, automotriz)""",

    "BOMBEO": """BOMBEO SOLAR (CAPTACIÓN Y APLICACIÓN HIDRÁULICA)
23 — https://www.aisa.com.gt/shop/category/bombas-perifericas-8 (bomba periférica, presurizador)
24 — https://www.aisa.com.gt/shop/category/bombas-sumergibles-bajo-caudal-9 (sumergible, bomba pozo)
25 — https://www.aisa.com.gt/shop/category/bombas-de-caudal-11 (caudal, irrigación)
26 — https://www.aisa.com.gt/shop/category/bomba-presurizadora-35 (presurizadora, booster, presión)
27 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-34 (recirculación, loop pump)
28 — https://www.aisa.com.gt/shop/category/bombas-superficiales-10 (superficial, aspiración)
29 — https://www.aisa.com.gt/shop/category/bombas-multietapas-12 (multietapa, vertical)
30 — https://www.aisa.com.gt/shop/category/bomba-solar-dc-13 (solar DC, bomba directa, sin batería)
31 — https://www.aisa.com.gt/shop/category/bomba-de-calor-36 (bomba calor, heat pump, piscina)
32 — https://www.aisa.com.gt/shop/category/estacion-de-bombeo-123 (estación, bombeo automatizado)""",

    "CALENTAMIENTO": """CALENTAMIENTO SOLAR TÉRMICO
33 — https://www.aisa.com.gt/shop/category/calentadores-solares-1 (calentador solar, boiler solar)
34 — https://www.aisa.com.gt/shop/category/calentadores-solares-deluxe-25 (deluxe, inoxidable)
35 — https://www.aisa.com.gt/shop/category/calentadores-solares-tubos-vacio-2 (tubos al vacío, invierno)
36 — https://www.aisa.com.gt/shop/category/calentadores-solares-placa-plana-3 (placa plana, tropical)
37 — https://www.aisa.com.gt/shop/category/termo-tanque-4 (termo, tanque, reservorio)
38 — https://www.aisa.com.gt/shop/category/accesorios-para-calentadores-5 (accesorios, instalación)""",

    "REFRIGERACION": """REFRIGERACIÓN Y CLIMATIZACIÓN
39 — https://www.aisa.com.gt/shop/category/refrigeracion-solar-14 (refrigerador solar, nevera)
40 — https://www.aisa.com.gt/shop/category/congelador-solar-64 (freezer solar, congelador, hielo)
56 — https://www.aisa.com.gt/shop/category/compresor-68 (compresor, motor compresor)
57 — https://www.aisa.com.gt/shop/category/fan-coil-69 (fan coil, aire acondicionado)
58 — https://www.aisa.com.gt/shop/category/evaporadores-y-condensadores-70 (evaporador, condensador)
59 — https://www.aisa.com.gt/shop/category/termostatos-y-controles-71 (termostato, control HVAC)""",

    "ACCESORIOS": """CABLES, PROTECCIONES Y ACCESORIOS
44 — https://www.aisa.com.gt/shop/category/cables-cable-solar-37 (cable solar, conductor fotovoltaico)
46 — https://www.aisa.com.gt/shop/category/cables-cable-sumergible-101 (cable sumergible, waterproof)
49 — https://www.aisa.com.gt/shop/category/conectores-mc4-62 (MC4, conector solar)
50 — https://www.aisa.com.gt/shop/category/flipones-61 (breaker, flipón, protección)
60 — https://www.aisa.com.gt/shop/category/estructuras-soporte-43 (estructura, soporte, montaje solar)
64 — https://www.aisa.com.gt/shop/category/tuberias-y-conexiones-29 (tubería, codo, te, hidráulica)
65 — https://www.aisa.com.gt/shop/category/valvulas-y-llaves-de-paso-30 (válvula, llave paso)""",

    "KITS": """KITS Y SOLUCIONES INTEGRADAS
69 — https://www.aisa.com.gt/shop/category/kit-solar-16 (kit solar, sistema completo, pre-armado)
70 — https://www.aisa.com.gt/shop/category/kit-bombeo-solar-124 (kit bombeo, agua solar, riego)"""
}

def obtener_fragmento_ontologia(topologia: Optional[str]) -> str:
    """Inyecta solo los bloques de la ontología necesarios para el contexto actual."""
    if not topologia:
        return "\n\n".join([ONTOLOGIA_BLOQUES["PANELES"], ONTOLOGIA_BLOQUES["BOMBEO"], ONTOLOGIA_BLOQUES["CALENTAMIENTO"], ONTOLOGIA_BLOQUES["KITS"]])
    
    bloques_requeridos = []
    if "On-Grid" in topologia:
        bloques_requeridos = ["PANELES", "INVERSORES", "CONTROLADORES", "ACCESORIOS", "KITS"]
    elif "Off-Grid" in topologia:
        bloques_requeridos = ["PANELES", "INVERSORES", "CONTROLADORES", "BATERIAS", "ACCESORIOS", "KITS"]
    elif "Bombeo" in topologia:
        bloques_requeridos = ["BOMBEO", "PANELES", "ACCESORIOS", "KITS"]
    elif "Calentamiento" in topologia:
        bloques_requeridos = ["CALENTAMIENTO", "ACCESORIOS"]
    elif "Refrigeración" in topologia or "Hielo" in topologia:
        bloques_requeridos = ["REFRIGERACION", "PANELES", "BATERIAS", "INVERSORES"]
    else:
        bloques_requeridos = list(ONTOLOGIA_BLOQUES.keys()) # Fallback: Enviar todo
        
    return "\n\n".join([ONTOLOGIA_BLOQUES[b] for b in bloques_requeridos])

# =====================================================================
# 4. HERRAMIENTAS
# =====================================================================
@tool
def procesar_oportunidad_backend(nombre_apellidos: str, departamento_municipio: str, consumo_actual: str, empresa_electrica: str, definicion_necesidad: str, listado_equipos_html: str, numero_whatsapp: str, resumen_18_palabras: str) -> str:
    """
    Ejecuta esta herramienta SOLO cuando el cliente acepte el pre-cálculo y el listado de equipos con links.
    Se encarga de enviar el WhatsApp y el Email al Controller a través de SMTP y AcruxLab.
    """
    num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
    controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
    
    status_email = "Pendiente"
    try:
        msg = MIMEMultipart()
        msg['From'] = os.getenv("SMTP_USER")
        msg['To'] = controller_email
        msg['Subject'] = resumen_18_palabras
        
        cuerpo_correo = f"""Oportunidad Generada:
- Cliente: {nombre_apellidos}
- Ubicación: {departamento_municipio}
- Consumo Actual: {consumo_actual}
- Empresa Eléctrica: {empresa_electrica}
- Definición de Necesidad: {definicion_necesidad}

Equipos Sugeridos (Solo equipos principales):
{listado_equipos_html}

Observaciones:
El cliente ha validado los links. Pendiente de cotizar materiales de instalación, mano de obra, fletes y viáticos por el Controller.
"""
        msg.attach(MIMEText(cuerpo_correo, 'plain'))
        
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            server.send_message(msg)
            
        status_email = "Email SMTP enviado correctamente."
    except Exception as e:
        status_email = f"Error en Email SMTP: {str(e)}"
        print(status_email) 
        
    payload_wa = {
        "instance_id": APICHAT_INSTANCE,
        "number": num_limpio,
        "text": f"🚨 Lead Aprobado: {nombre_apellidos}\nAsunto: {resumen_18_palabras}\nUbicación: {departamento_municipio}\nEquipos:\n{listado_equipos_html}"
    }
    headers_wa = {"Authorization": f"Bearer {APICHAT_TOKEN}", "Content-Type": "application/json"}
    
    try:
        response_wa = requests.post(APICHAT_ENDPOINT, json=payload_wa, headers=headers_wa, timeout=15)
        if response_wa.status_code in [200, 201]:
            return f"¡Excelente! He enviado tu solicitud vía email y WhatsApp al equipo de ingeniería de AISA. ({status_email})"
        else:
            return f"Error WA: {response_wa.status_code}. Info Email: {status_email}"
    except Exception as e:
        return f"Error general en WhatsApp: {str(e)}. Info Email: {status_email}"

# =====================================================================
# 5. MANEJADOR GLOBAL DE ERRORES EN TIEMPO DE EJECUCIÓN (BOUNDARY)
# =====================================================================
def notificar_error_runtime(error_obj, traceback_str, session_data, prompt_fallido):
    controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
    msg = MIMEMultipart()
    msg['From'] = os.getenv("SMTP_USER")
    msg['To'] = controller_email
    msg['Subject'] = f"🚨 ERROR CRÍTICO JARVI - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    try:
        session_json = json.dumps(session_data, indent=2, default=str)
    except Exception:
        session_json = str(session_data)

    cuerpo_correo = f"""Se ha detectado una excepción no controlada en tiempo de ejecución.
TIPO DE ERROR: {type(error_obj).__name__}
MENSAJE: {str(error_obj)}
ÚLTIMO PROMPT INTENTADO:
{prompt_fallido}
TRACEBACK COMPLETO:
--------------------------------------------------
{traceback_str}
--------------------------------------------------
CONTEXTO DE LA SESIÓN AL MOMENTO DEL ERROR:
{session_json}"""
    msg.attach(MIMEText(cuerpo_correo, 'plain'))
    
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            server.send_message(msg)
        print("Notificación de error enviada al administrador exitosamente.")
    except Exception as e_smtp:
        print(f"FALLO CRÍTICO: No se pudo enviar el correo de error. Razón: {e_smtp}")
        print(f"Traza original:\n{traceback_str}")

# =====================================================================
# 6. MOTOR COGNITIVO (INTEGRACIÓN PROTOCOLO C & NUEVA DIRECTRIZ)
# =====================================================================
graph_builder = StateGraph(AgentState)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])

# NODO 1: CLASIFICADOR EPITEMOLÓGICO
def clasificador_topologia_node(state: AgentState):
    messages = state.get("messages", [])
    ctx = state.get("contexto_tecnico", {
        "ciudad": None, "empresa_electrica": None, 
        "tarifa_base_gtq": None, "topologia": None, 
        "calculo_carga_completado": False, "requiere_auditoria_electrica": False
    })
    
    if not messages: return {"contexto_tecnico": ctx}
    
    ultimo_mensaje = messages[-1].content.lower()
  
    if not ctx.get("topologia"):
        if any(k in ultimo_mensaje for k in ["red", "atado", "interconectado", "ahorro", "eegsa", "factura"]):
            ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
            ctx["requiere_auditoria_electrica"] = True
        elif any(k in ultimo_mensaje for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
            ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
            ctx["requiere_auditoria_electrica"] = True
        elif any(k in ultimo_mensaje for k in ["bomba", "pozo", "caudal", "riego", "sumergible"]):
            ctx["topologia"] = "Bombeo Solar"
            ctx["requiere_auditoria_electrica"] = False
        elif any(k in ultimo_mensaje for k in ["calentador", "boiler", "agua caliente", "tubo", "termo"]):
            ctx["topologia"] = "Calentamiento Solar Térmico"
            ctx["requiere_auditoria_electrica"] = False
        elif any(k in ultimo_mensaje for k in ["hielo", "ice maker", "hielera", "refrigeración"]):
            ctx["topologia"] = "Refrigeración y Hielo"
            ctx["requiere_auditoria_electrica"] = False

    return {"contexto_tecnico": ctx}

# NODO 2: VALIDADOR DE DOMINIO DE MERCADO
def validador_geolocalizacion_node(state: AgentState):
    ctx = state.get("contexto_tecnico", {
        "ciudad": None, "empresa_electrica": None, 
        "tarifa_base_gtq": None, "topologia": None, 
        "calculo_carga_completado": False, "requiere_auditoria_electrica": False
    })
    messages = state.get("messages", [])
    if not messages: return {"contexto_tecnico": ctx}
    
    ultimo_mensaje = messages[-1].content.lower()
    
    if not ctx.get("ciudad"):
        if any(k in ultimo_mensaje for k in ["guatemala", "mixco", "capital", "ciudad", "villa nueva", "petapa"]):
            ctx["ciudad"] = "Guatemala Metropolitana"
            # Asignación condicionada a la topología
            if ctx.get("requiere_auditoria_electrica"):
                ctx["empresa_electrica"] = "EEGSA"
                ctx["tarifa_base_gtq"] = 1.45
        elif any(k in ultimo_mensaje for k in ["quetzaltenango", "xela", "coban", "escuintla", "petén", "peten", "zacapa", "chiquimula", "jutiapa", "izabal"]):
            ctx["ciudad"] = "Departamentos (Interior)"
            if ctx.get("requiere_auditoria_electrica"):
                ctx["empresa_electrica"] = "ENERGUATE (DEOCSA/DEORSA)"
                ctx["tarifa_base_gtq"] = 1.95
            
    return {"contexto_tecnico": ctx}

# NODO 3: MOTOR JARVI (PROMPT DINÁMICO REFINADO)
def chatbot_node(state: AgentState):
    ctx = state.get("contexto_tecnico", {
        "ciudad": None, "empresa_electrica": None, 
        "tarifa_base_gtq": None, "topologia": None, 
        "calculo_carga_completado": False, "requiere_auditoria_electrica": False
    })
    
    # Ruteo Epistemológico: Qué datos exigir según la topología
    if ctx.get("requiere_auditoria_electrica"):
        regla_datos = "1. DEBES recopilar sutilmente: Nombre y Apellido, Departamento y Municipio, Consumo actual (kWh o gasto mensual), Empresa eléctrica, y Definición exacta de su necesidad."
    else:
        regla_datos = "1. DEBES recopilar sutilmente: Nombre y Apellido, Departamento y Municipio, y Definición exacta de su necesidad. OMITIR POR COMPLETO Y NO PREGUNTAR sobre consumo actual en kWh ni empresa eléctrica, ya que es irrelevante para este tipo de producto. (Si llamas a la herramienta final, envía 'N/A' en estos campos)."

    # Optimización de Ventana de Contexto
    ontologia_dinamica = obtener_fragmento_ontologia(ctx.get('topologia'))
    
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa experto de AISA Solar.
    Tu misión es diagnosticar, diseñar y presupuestar soluciones energéticas utilizando el portafolio de AISA.
    [DATOS FIRMADOS Y VALIDADOS EN PRODUCCIÓN (PROTOCOLO C)]:
    - Ubicación del Proyecto: {ctx.get('ciudad') if ctx.get('ciudad') else 'PENDIENTE DE VALIDAR'}
    - Distribuidora del Servicio: {ctx.get('empresa_electrica') if ctx.get('empresa_electrica') else ('N/A' if not ctx.get('requiere_auditoria_electrica') else 'PENDIENTE DE VALIDAR')}
    - Tarifa indexada al sistema: GTQ {ctx.get('tarifa_base_gtq') if ctx.get('tarifa_base_gtq') else ('N/A' if not ctx.get('requiere_auditoria_electrica') else 'PENDIENTE')} /kWh
    - Topología Tecnológica Solicitada: {ctx.get('topologia') if ctx.get('topologia') else 'PENDIENTE DE DETECTAR'}

    REGLA DE CONDUCCIÓN COGNITIVA ESTRICTA:
    {regla_datos}
    2. Al presentar los equipos, es OBLIGATORIO incluir el enlace oficial de la Ontología para que el cliente pueda verlo en línea y validarlo.
    3. Cada línea de producto sugerido deberá llevar su código de producto (si es inferible), una pequeña descripción, el link oficial y un precio de lista estimado en Quetzales basado en la ontología.
    4. NO DEBES calcular totales de proyecto en la cotización.

    NUEVAS DIRECTRICES DE JUNTA DIRECTIVA (MANDATORIO):
    - EXENCIÓN DE RESPONSABILIDAD: Al presentar la propuesta con los links, DEBES incluir OBLIGATORIAMENTE Y TEXTUALMENTE el siguiente párrafo: 
      "Esta propuesta contempla ÚNICAMENTE el suministro de los equipos principales listados. Los cálculos de materiales de instalación, mano de obra, fletes, viáticos y demás servicios añadidos serán procesados y sumados exclusivamente por el asesor humano en la siguiente fase."
    - CIERRE Y DESPEDIDA: Tras la validación en línea del cliente, despídete agradeciendo e indícale claramente: "Recibirás contacto por WhatsApp de nuestro vendedor a la brevedad. En breve serás procesado y atendido por un operador."
    - HERRAMIENTA FINAL: Utiliza la herramienta `procesar_oportunidad_backend` para notificar al Controller humano ({os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")}).
    El parámetro `resumen_18_palabras` DEBE SER EXACTAMENTE DE 18 PALABRAS resumiendo la solución técnica que necesita el cliente.

    POLÍTICA DE MARCA (OBLIGATORIO):
    - NO menciones marcas de la competencia bajo ninguna circunstancia.
    - Actúa como un experto consultor, no como un formulario.
    - Tu base de conocimiento está estrictamente limitada EXCLUSIVAMENTE a la siguiente Ontología.

    ONTOLOGÍA DEL ECOSISTEMA AISA SOLAR (FILTRADA PARA ESTA SESIÓN):
    {ontologia_dinamica}
    """)
    return {"messages": [llm.invoke([prompt_sistema] + state["messages"])]}

# ENSAMBLAJE DEL GRAFO DIRIGIDO
graph_builder.add_node("clasificador", clasificador_topologia_node)
graph_builder.add_node("validador", validador_geolocalizacion_node)
graph_builder.add_node("chatbot", chatbot_node)
graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))

graph_builder.add_edge(START, "clasificador")
graph_builder.add_edge("clasificador", "validador")
graph_builder.add_edge("validador", "chatbot")
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")

jarvi_graph = graph_builder.compile(checkpointer=memory)

# =====================================================================
# 7. TÍTULO E INSTRUCCIONES (UI)
# =====================================================================
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""
    ¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**. Para obtener la mejor asesoría, realizaremos estos pasos:
    * **1. Descubrimiento:** Identificamos tus necesidades reales, ubicación y consumo.
    * **2. Análisis Técnico:** Calculamos tus requerimientos base.
    * **3. Especificación:** Seleccionamos equipos con **enlaces directos** para tu validación.
    * **4. Presupuesto:** Generamos la lista base en GTQ (sin costos de instalación).
    * **5. Contacto directo:** Tras definir tu solución, enviaré la solicitud formal a nuestro Controller y te contactaremos por WhatsApp.
    """)

# Variables de estado
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "is_voice_mode" not in st.session_state:
    st.session_state.is_voice_mode = False
if "audio_key_counter" not in st.session_state:
    st.session_state.audio_key_counter = 0
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

if "messages" not in st.session_state:
    greeting = """¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar. Estamos para ayudarte a encontrar la mejor solución energética. ¿Sobre qué producto necesitas información hoy?

1. Calentadores Solares
2. Paneles Solares (Fuera de la red / lugares sin energía)
3. Paneles Solares (Ahorro en factura eléctrica)
4. Bombas de Agua Solares
5. Bombas de Calor para piscinas
6. Máquinas de hacer hielo (Ice Maker)
7. Hieleras

Cuéntame qué te interesa y, para darte una atención personalizada, ¿podrías indicarme también tu nombre y en qué zona te encuentras?"""
    
    st.session_state.messages = [AIMessage(content=greeting)]
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    
    estado_inicial = {
        "messages": [AIMessage(content=greeting)],
        "contexto_tecnico": {
            "ciudad": None,
            "empresa_electrica": None,
            "tarifa_base_gtq": None,
            "topologia": None,
            "calculo_carga_completado": False,
            "requiere_auditoria_electrica": False
        }
    }
    jarvi_graph.update_state(config, estado_inicial)

# Renderizado del historial
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage): st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage): st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage): st.chat_message("system").markdown(f"⚙️ Operación: {msg.content}")

# =====================================================================
# LÓGICA DE CAPTURA DUAL: AUDIO Y TEXTO
# =====================================================================
audio_value = st.audio_input(
    "🎤 Grabar mensaje de voz", 
    key=f"audio_input_{st.session_state.audio_key_counter}"
)

text_value = st.chat_input("¿Qué solución necesitas hoy: paneles, bombeo o respaldo? Cuéntame ubicación, consumo y si buscas ahorro, autonomía o continuidad.")

prompt = None

if text_value:
    st.session_state.is_voice_mode = False
    prompt = text_value

elif audio_value is not None:
    st.session_state.is_voice_mode = True
    with st.spinner("Escuchando tu mensaje de voz..."):
        try:
            audio_value.name = "audio.wav"
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_value
            )
            st.session_state.pending_prompt = transcript.text
            st.session_state.audio_key_counter += 1
            st.rerun()
        except Exception as e:
            st.error(f"Error al transcribir el audio: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None 

# =====================================================================
# PROCESAMIENTO COGNITIVO DEL AGENTE CON MANEJO DE ERRORES (BOUNDARY)
# =====================================================================
if prompt:
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Consultando en tiempo real con nuestro equipo de ingeniería especializada..."):
            try:
                config = {"configurable": {"thread_id": st.session_state.thread_id}}
                response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=prompt)]}, config)
                
                new_messages = response_state["messages"][len(st.session_state.messages)-1:]
        
                for msg in new_messages:
                    if isinstance(msg, AIMessage) and msg.content:
                        st.markdown(msg.content)
                        if st.session_state.is_voice_mode:
                            with st.spinner("Generando respuesta de voz..."):
                                try:
                                    speech_response = client.audio.speech.create(
                                        model="tts-1",
                                        voice="alloy",
                                        input=msg.content
                                    )
                                    audio_buffer = io.BytesIO()
                                    for chunk in speech_response.iter_bytes(chunk_size=4096):
                                        audio_buffer.write(chunk)
                                    audio_buffer.seek(0)
                                    st.audio(audio_buffer, format="audio/mp3", autoplay=True)
                                except Exception as e:
                                    st.error(f"Fallo en síntesis de voz: {e}")
                    elif isinstance(msg, ToolMessage):
                        st.markdown(f"⚙️ {msg.content}")
                
                st.session_state.messages = response_state["messages"]

            except Exception as e:
                tb_str = traceback.format_exc()
                estado_actual = {}
                try:
                    estado_grafo = jarvi_graph.get_state(config)
                    estado_actual = estado_grafo.values.get("contexto_tecnico", {})
                except Exception:
                    estado_actual = "No se pudo recuperar el estado del grafo."

                session_snapshot = {
                    "thread_id": st.session_state.get("thread_id", "Desconocido"),
                    "is_voice_mode": st.session_state.get("is_voice_mode", False),
                    "contexto_tecnico": estado_actual,
                    "cantidad_mensajes_historial": len(st.session_state.get("messages", []))
                }

                notificar_error_runtime(e, tb_str, session_snapshot, prompt)
                st.error("Ha ocurrido un problema técnico inesperado procesando tu solicitud.")
                st.warning("Nuestro equipo de ingeniería ya ha sido notificado con los detalles del error. Por favor, intenta reformular tu pregunta o comunícate vía WhatsApp directamente.")
