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
# 1. DEFINICIÓN DEL ESTADO (ACTUALIZADO - PROTOCOLO C)
# =====================================================================
class InferenciaEnergetica(TypedDict):
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    contexto_tecnico: InferenciaEnergetica  # Estado Fuertemente Tipado

# =====================================================================
# 2. CONFIGURACIÓN Y PERSISTENCIA
# =====================================================================
load_dotenv()

# Variables para API de Acruxlab / Odoo
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")

# Instancia global del cliente OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

@st.cache_resource
def get_memory():
    return MemorySaver()

memory = get_memory()

# =====================================================================
# 3. ONTOLOGÍA INTEGRAL (70 CATEGORÍAS)
# =====================================================================
ONTOLOGIA_AISA = """
ENERGÍA SOLAR (CAPTACIÓN FOTOVOLTAICA)
1 — https://www.aisa.com.gt/shop/category/paneles-solares-18 (panel solar, placa solar, módulo fotovoltaico, plaquita, panel)
2 — https://www.aisa.com.gt/shop/category/paneles-solares-monocristalinos-19 (monocristalino, mono panel, alta eficiencia, premium solar, panel negro)
3 — https://www.aisa.com.gt/shop/category/paneles-solares-policristalinos-20 (policristalino, poli panel, económico, eficiencia media, panel azul)
4 — https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7 (on-grid, interconectado, net metering, solar urbano, ahorro energético)
5 — https://www.aisa.com.gt/shop/category/sistemas-aislados-17 (off-grid, aislado, solar rural, independiente, kit autónomo)
6 — https://www.aisa.com.gt/shop/category/sistemas-hibridos-96 (híbrido, backup solar, inteligente, respaldo, smart solar)

CONVERSIÓN ENERGÉTICA (INVERSORES Y TRANSFORMADORES)
7 — https://www.aisa.com.gt/shop/category/inversores-22 (inverter, inversor, convertidor, caja solar, cerebro del sistema)
8 — https://www.aisa.com.gt/shop/category/inversor-hibrido-67 (hybrid inverter, híbrido, backup, inversor smart, pro)
9 — https://www.aisa.com.gt/shop/category/micro-inv-45 (microinverter, micro, optimizador, inversor panel, micro solar)
10 — https://www.aisa.com.gt/shop/category/inversor-carga-23 (inversor cargador, inverter charger, combo, integrado, todo en uno)
11 — https://www.aisa.com.gt/shop/category/inversor-senoidal-pura-24 (senoidal, onda pura, calidad eléctrica, electrónica segura, inverter premium)
12 — https://www.aisa.com.gt/shop/category/inversor-senoidal-modificada-25 (onda modificada, básico, económico, motor, herramienta eléctrica)

CONTROL Y GESTIÓN DE ENERGÍA
13 — https://www.aisa.com.gt/shop/category/controladores-15 (controlador, regulador, cargador, controlador solar, regulador carga)
14 — https://www.aisa.com.gt/shop/category/controlador-mppt-39 (MPPT, controlador avanzado, smart controller, max power, premium)
15 — https://www.aisa.com.gt/shop/category/controlador-pwm-40 (PWM, controlador básico, regulador simple, económico, entry level)
16 — https://www.aisa.com.gt/shop/category/medidores-de-energia-42 (medidor, monitor, wattmeter, energía, consumo)

ALMACENAMIENTO ENERGÉTICO
17 — https://www.aisa.com.gt/shop/category/baterias-solares-21 (batería solar, banco, acumulador, battery bank, reserva)
18 — https://www.aisa.com.gt/shop/category/baterias-solares-bateria-de-gel-26 (gel battery, batería gel, sellada, AGM, acumulador sin mantenimiento)
19 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-backup-105 (backup battery, UPS battery, respaldo, emergencia, batería de respaldo)
20 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-litio-106 (li-ion, litio, batería moderna, alta performance, liviana)
21 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-estacionarias-27 (estacionaria, industrial, descarga profunda, ciclo profundo, fosca)
22 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-arranque-28 (arranque, starter, automotriz, motor, battery start)

BOMBEO SOLAR (CAPTACIÓN Y APLICACIÓN HIDRÁULICA)
23 — https://www.aisa.com.gt/shop/category/bombas-perifericas-8 (bomba periférica, presurizador, booster, bombita, presión de agua)
24 — https://www.aisa.com.gt/shop/category/bombas-sumergibles-bajo-caudal-9 (sumergible, bomba pozo, deep well, saca agua, pozo profundo)
25 — https://www.aisa.com.gt/shop/category/bombas-de-caudal-11 (caudal, bomba grande, irrigación, flow pump, caudalera)
26 — https://www.aisa.com.gt/shop/category/bomba-presurizadora-35 (presurizadora, booster, presión, empujador, bomba de casa)
27 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-34 (recirculación, loop pump, retorno, agua caliente, circulation constante)
28 — https://www.aisa.com.gt/shop/category/bombas-superficiales-10 (superficial, aspiración, pozo somero, agua superficial, jet pump)
29 — https://www.aisa.com.gt/shop/category/bombas-multietapas-12 (multietapa, vertical, alta presión, cascada, water booster)
30 — https://www.aisa.com.gt/shop/category/bomba-solar-dc-13 (solar DC, bomba directa, sin batería, eficiente, solar pump)
31 — https://www.aisa.com.gt/shop/category/bomba-de-calor-36 (bomba calor, heat pump, piscina, calefacción, agua templada)
32 — https://www.aisa.com.gt/shop/category/estacion-de-bombeo-123 (estación, bombeo automatizado, skid, control, hidroneumático)

CALENTAMIENTO SOLAR TÉRMICO
33 — https://www.aisa.com.gt/shop/category/calentadores-solares-1 (calentador solar, boiler solar, termo solar, agua caliente, termosifón)
34 — https://www.aisa.com.gt/shop/category/calentadores-solares-deluxe-25 (deluxe, premium heater, inoxidable, calentador pro, alta gama)
35 — https://www.aisa.com.gt/shop/category/calentadores-solares-tubos-vacio-2 (tubos al vacío, vacío, alta temperatura, invierno, heat pipe)
36 — https://www.aisa.com.gt/shop/category/calentadores-solares-placa-plana-3 (placa plana, colector plano, tropical, económico, tradicional)
37 — https://www.aisa.com.gt/shop/category/termo-tanque-4 (termo, tanque, reservorio, agua caliente, deposito térmico)
38 — https://www.aisa.com.gt/shop/category/accesorios-para-calentadores-5 (accesorios, instalación, tubería, conexiones, soportes calentador)

REFRIGERACIÓN SOLAR
39 — https://www.aisa.com.gt/shop/category/refrigeracion-solar-14 (solar fridge, refrigerador solar, nevera solar, enfriador, conservación)
40 — https://www.aisa.com.gt/shop/category/congelador-solar-64 (freezer solar, congelador, cold storage, nevera solar, hielo)

ILUMINACIÓN EFICIENTE
41 — https://www.aisa.com.gt/shop/category/iluminacion-dc-6 (bombilla DC, luz solar, foco LED, bombillo, iluminación eficiente)
42 — https://www.aisa.com.gt/shop/category/iluminacion-led-65 (LED, iluminación, ahorro, luz blanca, bombilla larga duración)
43 — https://www.aisa.com.gt/shop/category/lamparas-solares-portatiles-66 (portátil, lámpara solar, camping, emergencia, linterna solar)

CABLEADO Y CONDUCCIÓN ELÉCTRICA
44 — https://www.aisa.com.gt/shop/category/cables-cable-solar-37 (cable solar, cable PV, cable panel, alambre solar, conductor fotovoltaico)
45 — https://www.aisa.com.gt/shop/category/cables-cable-bateria-100 (battery cable, cable batería, cable grueso, conductor DC, potencia)
46 — https://www.aisa.com.gt/shop/category/cables-cable-sumergible-101 (cable sumergible, cable pozo, waterproof cable, sumergible, pozo profundo)
47 — https://www.aisa.com.gt/shop/category/cables-accesorios-para-cable-38 (accesorios cable, sujetadores, cinta eléctrica, organizador, canaleta)
48 — https://www.aisa.com.gt/shop/category/terminales-y-conectores-63 (terminal, conector, lug, ojal, crimp)

PROTECCIONES Y SEGURIDAD ELÉCTRICA
49 — https://www.aisa.com.gt/shop/category/conectores-mc4-62 (MC4, conector solar, terminal, plug solar, acople rápido)
50 — https://www.aisa.com.gt/shop/category/flipones-61 (breaker, flipón, protection, interruptor, automático termomagnético)
51 — https://www.aisa.com.gt/shop/category/fusibles-60 (fusible, protección, sobrecarga, cartucho, safety)
52 — https://www.aisa.com.gt/shop/category/sistemas-de-tierra-59 (tierra, grounding, jabalina, varilla, protección eléctrica)
53 — https://www.aisa.com.gt/shop/category/canaletas-y-organizadores-102 (canaleta, organizador, tubería conduit, PVC, protección cables)

EÓLICA Y OTRAS RENOVABLES
54 — https://www.aisa.com.gt/shop/category/turbinas-eolicas-20 (turbina eólica, wind turbine, molino, aerogenerador, eólico)
55 — https://www.aisa.com.gt/shop/category/controladores-eolicos-41 (controlador eólico, regulador viento, wind controller, aerogenerador control)

HVAC Y SISTEMAS INDUSTRIALES
56 — https://www.aisa.com.gt/shop/category/compresor-68 (compresor, compressor, aire comprimido, motor compresor, compresión industrial)
57 — https://www.aisa.com.gt/shop/category/fan-coil-69 (fan coil, climatizador, serpentín, ventilador, aire acondicionado)
58 — https://www.aisa.com.gt/shop/category/evaporadores-y-condensadores-70 (evaporador, condensador, intercambiador, calor, refrigeración)
59 — https://www.aisa.com.gt/shop/category/termostatos-y-controles-71 (termostato, control temperatura, climatización, automático, HVAC control)

ACCESORIOS E INSTALACIÓN
60 — https://www.aisa.com.gt/shop/category/estructuras-soporte-43 (estructura, soporte, rail, perfil, montaje solar)
61 — https://www.aisa.com.gt/shop/category/flipones-caja-de-conexion-104 (caja conexión, gabinete, centro de carga, panel eléctrico, distribuidor)
62 — https://www.aisa.com.gt/shop/category/herramientas-103 (herramienta, crimpador, pelacables, multímetro, instalación)
63 — https://www.aisa.com.gt/shop/category/fijaciones-y-tornilleria-44 (tornillo, anclaje, fijación, soporte, montaje)

ACCESORIOS HIDRÁULICOS
64 — https://www.aisa.com.gt/shop/category/tuberias-y-conexiones-29 (tubería, conexión, codo, te, reducción, hidráulica)
65 — https://www.aisa.com.gt/shop/category/valvulas-y-llaves-de-paso-30 (válvula, llave paso, check, compuerta, regulación flujo)
66 — https://www.aisa.com.gt/shop/category/filtros-y-purificadores-31 (filtro, purificador, sedimentos, agua limpia, protección bomba)
67 — https://www.aisa.com.gt/shop/category/flotadores-y-controladores-32 (flotador, controlador nivel, tanque, llenado automático, sensor)
68 — https://www.aisa.com.gt/shop/category/presostatos-y-manometros-33 (presostato, manómetro, presión, regulador, control hidráulico)

KITS Y SOLUCIONES INTEGRADAS
69 — https://www.aisa.com.gt/shop/category/kit-solar-16 (kit solar, sistema completo, pre-armado, llave en mano, paquete solar)
70 — https://www.aisa.com.gt/shop/category/kit-bombeo-solar-124 (kit bombeo, solar pump, agua solar, riego autónomo, ganadero)
"""

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
    
    # 1. Preparación y Envío del Correo vía SMTP nativo
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
El cliente ha validado los links.
Pendiente de cotizar materiales de instalación, mano de obra, fletes y viáticos por el Controller.
"""
        msg.attach(MIMEText(cuerpo_correo, 'plain'))
        
        # Conexión y envío
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            server.send_message(msg)
            
        status_email = "Email SMTP enviado correctamente."
    except Exception as e:
        status_email = f"Error en Email SMTP: {str(e)}"
        print(status_email) # Log interno para el contenedor
        
    # 2. Notificación WhatsApp vía Odoo/Acruxlab
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
    """
    Captura la traza del error y el contexto de la sesión para enviarlo por correo al Controller.
    """
    controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
    
    msg = MIMEMultipart()
    msg['From'] = os.getenv("SMTP_USER")
    msg['To'] = controller_email
    msg['Subject'] = f"🚨 ERROR CRÍTICO JARVI - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # Formatear el contexto técnico y la sesión para que sea legible
    try:
        session_json = json.dumps(session_data, indent=2, default=str)
    except Exception:
        session_json = str(session_data)

    cuerpo_correo = f"""
Se ha detectado una excepción no controlada en tiempo de ejecución.

TIPO DE ERROR: {type(error_obj).__name__}
MENSAJE: {str(error_obj)}

ÚLTIMO PROMPT INTENTADO:
{prompt_fallido}

TRACEBACK COMPLETO:
--------------------------------------------------
{traceback_str}
--------------------------------------------------

CONTEXTO DE LA SESIÓN AL MOMENTO DEL ERROR:
{session_json}
"""
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
        # Fallback al log estándar del contenedor si el correo también falla
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
        "calculo_carga_completado": False
    })
    
    if not messages: return {"contexto_tecnico": ctx}
    
    ultimo_mensaje = messages[-1].content.lower()
  
    if not ctx.get("topologia"):
        if any(k in ultimo_mensaje for k in ["red", "atado", "interconectado", "ahorro", "eegsa"]):
            ctx["topologia"] = "On-Grid (Sistemas Atados a la Red)"
        elif any(k in ultimo_mensaje for k in ["aislado", "batería", "bateria", "finca", "autónomo", "off-grid"]):
            ctx["topologia"] = "Off-Grid (Sistemas Aislados)"
        elif any(k in ultimo_mensaje for k in ["bomba", "pozo", "caudal", "riego", "sumergible"]):
            ctx["topologia"] = "Bombeo Solar"
        elif any(k in ultimo_mensaje for k in ["calentador", "boiler", "agua caliente", "tubo", "termo"]):
            ctx["topologia"] = "Calentamiento Solar Térmico"

    return {"contexto_tecnico": ctx}

# NODO 2: VALIDADOR DE DOMINIO DE MERCADO
def validador_geolocalizacion_node(state: AgentState):
    ctx = state.get("contexto_tecnico", {
        "ciudad": None, "empresa_electrica": None, 
        "tarifa_base_gtq": None, "topologia": None, 
        "calculo_carga_completado": False
    })
    messages = state.get("messages", [])
    if not messages: return {"contexto_tecnico": ctx}
    
    ultimo_mensaje = messages[-1].content.lower()
    
    if not ctx.get("ciudad"):
        if any(k in ultimo_mensaje for k in ["guatemala", "mixco", "capital", "ciudad", "villa nueva", "petapa"]):
            ctx["ciudad"] = "Guatemala Metropolitana"
            ctx["empresa_electrica"] = "EEGSA"
            ctx["tarifa_base_gtq"] = 1.45
        elif any(k in ultimo_mensaje for k in ["quetzaltenango", "xela", "coban", "escuintla", "petén", "peten", "zacapa", "chiquimula", "jutiapa", "izabal"]):
            ctx["ciudad"] = "Departamentos (Interior)"
            ctx["empresa_electrica"] = "ENERGUATE (DEOCSA/DEORSA)"
            ctx["tarifa_base_gtq"] = 1.95
            
    return {"contexto_tecnico": ctx}

# NODO 3: MOTOR JARVI (PROMPT DINÁMICO REFINADO CON DIRECTRICES JD)
def chatbot_node(state: AgentState):
    ctx = state.get("contexto_tecnico", {
        "ciudad": None, "empresa_electrica": None, 
        "tarifa_base_gtq": None, "topologia": None, 
        "calculo_carga_completado": False
    })
    
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa experto de AISA Solar.
    Tu misión es diagnosticar, diseñar y presupuestar soluciones energéticas utilizando el portafolio de AISA.
    [DATOS FIRMADOS Y VALIDADOS EN PRODUCCIÓN (PROTOCOLO C)]:
    - Ubicación del Proyecto: {ctx.get('ciudad') if ctx.get('ciudad') else 'PENDIENTE DE VALIDAR'}
    - Distribuidora del Servicio: {ctx.get('empresa_electrica') if ctx.get('empresa_electrica') else 'PENDIENTE DE VALIDAR'}
    - Tarifa indexada al sistema: GTQ {ctx.get('tarifa_base_gtq') if ctx.get('tarifa_base_gtq') else 'PENDIENTE'} /kWh
    - Topología Tecnológica Solicitada: {ctx.get('topologia') if ctx.get('topologia') else 'PENDIENTE DE DETECTAR'}

    REGLA DE CONDUCCIÓN COGNITIVA ESTRICTA:
    1. A lo largo de la conversación, DEBES recopilar sutilmente la siguiente información del cliente antes de cerrar: Nombre y Apellido, Departamento y Municipio, Consumo actual (kWh o gasto mensual), Empresa eléctrica, y Definición exacta de su necesidad.
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
    - Tu base de conocimiento está estrictamente limitada EXCLUSIVAMENTE a la ONTOLOGÍA DE AISA SOLAR.
    ONTOLOGÍA DEL ECOSISTEMA AISA SOLAR:
    {ONTOLOGIA_AISA}
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

# FIX DEFINITIVO: Variable temporal para evitar el bloqueo del frontend
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

if "messages" not in st.session_state:
    # Se añade la petición inicial alineada a recopilar la información solicitada
    greeting = "¡Hola! 👋 Soy Jarvi, Ingeniero de Soluciones de AISA Solar. Para iniciar a definir tus necesidades, ¿podrías indicarme tu Nombre y Apellido, tu número de WhatsApp, y en qué departamento/municipio te encuentras para perfilar tu tarifa eléctrica?"
    st.session_state.messages = [AIMessage(content=greeting)]
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    
    # Se inyecta el Contexto Técnico en blanco desde la sesión inicial
    estado_inicial = {
        "messages": [AIMessage(content=greeting)],
        "contexto_tecnico": {
            "ciudad": None,
            "empresa_electrica": None,
            "tarifa_base_gtq": None,
            "topologia": None,
            "calculo_carga_completado": False
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

# 1. Si el usuario escribe texto, se procesa normalmente
if text_value:
    st.session_state.is_voice_mode = False
    prompt = text_value

# 2. Si el usuario envía audio, lo procesamos de inmediato y forzamos reinicio
elif audio_value is not None:
    st.session_state.is_voice_mode = True
    
    with st.spinner("Escuchando tu mensaje de voz..."):
        try:
            audio_value.name = "audio.wav"
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_value
            )
            # Guardamos la transcripción en la variable pendiente
            st.session_state.pending_prompt = transcript.text
            
            # Incrementamos la llave para que el widget se renderice limpio en la próxima pasada
            st.session_state.audio_key_counter += 1
            
            # Forzamos recarga INMEDIATA. Esto destruye el audio_value y limpia la interfaz.
            st.rerun()
            
        except Exception as e:
            st.error(f"Error al transcribir el audio: {e}")

# 3. Al recargar la página (gracias a st.rerun), recogemos el texto transcrito
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None # Limpiamos para no crear un bucle

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
                
                # Actualizar y renderizar historial
                new_messages = response_state["messages"][len(st.session_state.messages)-1:]
        
                for msg in new_messages:
                    if isinstance(msg, AIMessage) and msg.content:
                        st.markdown(msg.content)
                        
                        # SI EL USUARIO HABLÓ, LE RESPONDEMOS CON VOZ USANDO OPENAI TTS
                        if st.session_state.is_voice_mode:
                            with st.spinner("Generando respuesta de voz..."):
                                try:
                                    speech_response = client.audio.speech.create(
                                        model="tts-1",
                                        voice="alloy",
                                        input=msg.content
                                    )
                                    # Convertir stream a BytesIO para Streamlit
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
                # 1. Capturar la traza completa del error
                tb_str = traceback.format_exc()
                
                # 2. Recolectar datos vitales de la sesión
                estado_actual = {}
                try:
                    # Intentamos extraer el contexto técnico de LangGraph
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

                # 3. Notificar silenciosamente al backend vía correo
                notificar_error_runtime(e, tb_str, session_snapshot, prompt)

                # 4. Manejo de cara al usuario final para mantener la estabilidad del frontend
                st.error("Ha ocurrido un problema técnico inesperado procesando tu solicitud.")
                st.warning("Nuestro equipo de ingeniería ya ha sido notificado con los detalles del error. Por favor, intenta reformular tu pregunta o comunícate vía WhatsApp directamente.")
