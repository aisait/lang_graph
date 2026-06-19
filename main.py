# main.py
import streamlit as st
import os
import json
import requests
import uuid
from typing import Annotated, TypedDict, List
from dotenv import load_dotenv

# Componentes de LangChain / LangGraph
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# 1. CONFIGURACIÓN DE ENTORNO Y VARIABLES (Railway / Local)
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# 2. ONTOLOGÍA ESTRUCTURADA (Fuente Única de Verdad)
ONTOLOGIA_AISA = """
Marco Teórico: El sitemap de AISA revela una arquitectura funcional organizada en 7 capas ontológicas interdependientes:
CAPTACIÓN (Generación de energía primaria)
CONVERSIÓN (Transformación de energía)
CONTROL Y GESTIÓN (Regulación y optimización)
ALMACENAMIENTO (Reserva energética)
APLICACIÓN FINAL (Uso específico de energía)
TRANSMISIÓN (Infraestructura de conexión)
PROTECCIÓN (Seguridad y durabilidad)

Este modelo permite inferir intenciones de compra completas: no solo qué producto necesita el usuario, sino qué subsistema completo requiere para resolver su problema energético o hídrico.

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
43 — https://www.aisa.com.gt/shop/category/lamparas-solares-portatiles-66 (portátil, lámpara solar, camping, emergency, linterna solar)

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

# 3. DEFINICIÓN DEL ESTADO DEL GRAFO (Graph State)
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

# 4. HERRAMIENTAS (Tools) PARA EL LLM
@tool
def enviar_whatsapp_humano(nombre_cliente: str, numero_whatsapp: str, resumen_35_palabras: str, productos_links: str, presupuesto_estimado: str) -> str:
    """
    Ejecuta esta herramienta SOLO cuando el cliente acepte expresamente el presupuesto y solicite validación humana.
    Toma la información estructurada y la inyecta al ecosistema Odoo a través del API Gateway configurado.
    """
    num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
    
    mensaje_para_ingeniero = (
        f"🚨 *Nuevo Lead Calificado - Jarvi AISA Solar* 🚨\n\n"
        f"👤 *Cliente:* {nombre_cliente}\n"
        f"📱 *WhatsApp:* +{num_limpio}\n"
        f"🏢 *Instancia:* {APICHAT_INSTANCE}\n\n"
        f"📝 *Resumen de Necesidad:* {resumen_35_palabras}\n\n"
        f"🛒 *Solución Propuesta (Links):*\n{productos_links}\n\n"
        f"💰 *Presupuesto Estimado:* {presupuesto_estimado}\n\n"
        f"Por favor validar disponibilidad técnica y cotización formal de ingeniería."
    )

    payload = {
        "instance_id": APICHAT_INSTANCE,
        "number": num_limpio,
        "text": mensaje_para_ingeniero
    }
    
    headers = {
        "Authorization": f"Bearer {APICHAT_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(APICHAT_ENDPOINT, json=payload, headers=headers, timeout=15)
        
        if response.status_code in [200, 201]:
            return "¡Excelente! He enviado tu perfil y el presupuesto preliminar a nuestro equipo de ingenieros de AISA Solar. Un especialista revisará el diseño hidrosanitario/fotovoltaico y te contactará directamente por WhatsApp."
        else:
            return f"He registrado tus datos, pero la pasarela reportó un estado {response.status_code}. Un agente humano revisará la cola de mensajes manualmente."
    except Exception as e:
        return f"Error de comunicación de red: {str(e)}. No te preocupes, el historial queda registrado para revisión humana."

tools = [enviar_whatsapp_humano]

# 5. CONSTRUCCIÓN DE NODOS DEL GRAFO
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
llm_with_tools = llm.bind_tools(tools)

def chatbot_node(state: AgentState):
    """Nodo del motor cognitivo de Jarvi. Ejecuta las capas ontológicas."""
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa Experto de AISA Solar.
    
    ÁRBOL DE DECISIÓN OBLIGATORIO:
    1. CUALIFICACIÓN: Solicita Nombre completo, País (para deducir código de área) y WhatsApp.
    2. DIAGNÓSTICO: Analiza si requiere solución Fotovoltaica (Atada a red, aislada o híbrida), Térmica, Bombeo o Iluminación.
    3. MAPPING ONTOLÓGICO: Traduce la necesidad a los subsistemas correspondientes usando el catálogo adjunto.
    4. PRE-PRESUPUESTO: Genera un listado de productos con sus LINKS OFICIALES y un precio estimado sin mano de obra.
    5. CIERRE: Si el usuario aprueba, genera un resumen técnico de EXACTAMENTE 35 PALABRAS y activa la herramienta 'enviar_whatsapp_humano'.

    RESTRICCIONES OPERATIVAS:
    - Prohibido inventar categorías o URLs que no figuren en la Ontología, mencionar marcas ajenas y proveedores que no sean AISA.
    - El resumen final debe ser estrictamente sintético (35 palabras) para no saturar los logs de Odoo.
    
    ONTOLOGÍA DEL ECOSISTEMA AISA SOLAR:
    {ONTOLOGIA_AISA}
    """)
    messages = [prompt_sistema] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

# 6. CONFIGURACIÓN DEL GRAFO (LangGraph)
graph_builder = StateGraph(AgentState)
graph_builder.add_node("chatbot", chatbot_node)

tool_node = ToolNode(tools=tools)
graph_builder.add_node("tools", tool_node)

graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

# --- COMPILACIÓN CON EL CHECKPOINTER DE MEMORIA INTERNA ---
memory = MemorySaver()
jarvi_graph = graph_builder.compile(checkpointer=memory)

# 7. INTERFAZ DE USUARIO (Streamlit UI)
st.title("Jarvi ⚡ Agente de Soluciones de AISA")

with st.expander("ℹ️ Instrucciones de Operación"):
    st.markdown("""
    * **Identificación Inicial:** Proporciona tus datos básicos para habilitar el enrutamiento automático hacia un especialista.
    * **Precisión de Requerimiento:** Especifica si tu proyecto abarca captación energética, bombeo de agua profunda o climatización.
    """)

# Inicializar un ID de hilo persistente por sesión de navegador para LangGraph
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

# Inicialización y sincronización atómica del estado base de mensajes
if "messages" not in st.session_state:
    st.session_state.messages = []
    greeting = "¡Hola! 👋 Soy Jarvi, Ingeniero de Preventa Virtual de AISA Solar. Para iniciar nuestra evaluación técnica, ¿podrías indicarme tu Nombre completo, el País desde el que nos escribes y tu número de WhatsApp?"
    
    # Inyectar el saludo inicial directamente en la memoria persistente del Grafo
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    jarvi_graph.update_state(config, {"messages": [AIMessage(content=greeting)]})
    st.session_state.messages.append(AIMessage(content=greeting))

# Renderizado del flujo conversacional histórico
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage) and msg.content:
        st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").markdown(msg.content)  # Ajustado: extracción de contenido dinámico corregida
    elif isinstance(msg, ToolMessage):
        st.chat_message("system").markdown(f"⚙️ *Operación de Integración:* {msg.content}")

# 8. MANEJO DE INTERACCIÓN
if prompt := st.chat_input("¿Qué sistema de AISA Solar necesitas: Agua, Energía, Respaldo o Climatización?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Procesando matriz lógica en el grafo..."):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            
            # Pasamos únicamente el nuevo mensaje; LangGraph recupera el historial usando el checkpointer nativo
            response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=prompt)]}, config)
            
            # Sincronizamos los mensajes nuevos generados por el grafo de vuelta al estado de Streamlit
            new_messages = response_state["messages"][len(st.session_state.messages):]
            for msg in new_messages:
                if isinstance(msg, AIMessage) and msg.content:
                    st.markdown(msg.content)
                elif isinstance(msg, ToolMessage):
                    st.markdown(f"⚙️ *Operación de Integración:* {msg.content}")
            
            st.session_state.messages = response_state["messages"]
