import streamlit as st
import os
import requests
import uuid
from typing import Annotated, TypedDict
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# =====================================================================
# 1. DEFINICIÓN DEL ESTADO
# =====================================================================
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

# =====================================================================
# 2. CONFIGURACIÓN Y PERSISTENCIA
# =====================================================================
load_dotenv()
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")

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
def enviar_whatsapp_humano(nombre_cliente: str, numero_whatsapp: str, resumen_35_palabras: str, productos_links: str, presupuesto_estimado: str) -> str:
    """Ejecuta esta herramienta SOLO cuando el cliente acepte el presupuesto."""
    num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
    payload = {
        "instance_id": APICHAT_INSTANCE,
        "number": num_limpio,
        "text": f"🚨 Lead: {nombre_cliente}\nResumen: {resumen_35_palabras}\nLinks: {productos_links}\nPresupuesto: {presupuesto_estimado}"
    }
    headers = {"Authorization": f"Bearer {APICHAT_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.post(APICHAT_ENDPOINT, json=payload, headers=headers, timeout=15)
        return "¡Excelente! He enviado tu solicitud al equipo de ingeniería de AISA." if response.status_code in [200, 201] else f"Error: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

# =====================================================================
# 5. MOTOR COGNITIVO (SystemMessage CON POLÍTICA DE MARCA + D.E.S.I.G.N.-5)
# =====================================================================
graph_builder = StateGraph(AgentState)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([enviar_whatsapp_humano])

def chatbot_node(state: AgentState):
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa experto de AISA Solar. Tu misión es diagnosticar, diseñar y presupuestar soluciones energéticas utilizando el portafolio de AISA.

    Tu operativa interna sigue el protocolo técnico D.E.S.I.G.N.-5:
    1. Realiza un diagnóstico técnico fluido: indaga sobre la instalación, equipos necesarios y objetivos energéticos sin utilizar cuestionarios rígidos ni listar pasos.
    2. Calcula parámetros técnicos de carga antes de presentar cualquier propuesta. ¡PROHIBIDO COTIZAR SIN CÁLCULO DE CARGA!
    3. Mapea necesidades a los productos AISA usando la ontología provista.
    4. Verifica compatibilidad técnica antes de recomendar.
    5. Presenta presupuestos en Quetzales (GTQ) con ROI y justificación técnica.

    POLÍTICA DE MARCA (OBLIGATORIO):
    - NO menciones marcas de la competencia bajo ninguna circunstancia.
    - Si el usuario pregunta por otra marca, ignora la consulta y redirige a AISA Solar argumentando que somos la única solución con respaldo, garantía técnica y prestigio en la región.
    - Actúa como un experto consultor, no como un formulario.
    - Si el cliente presiona por precio sin haber completado el análisis técnico, responde: "Para garantizar la eficiencia de tu inversión y evitar sobredimensionamiento, primero debo realizar un diagnóstico energético preciso. Es nuestro estándar de calidad."
    - El resumen final de Cierre debe ser de EXACTAMENTE 35 PALABRAS.

    ONTOLOGÍA DEL ECOSISTEMA AISA SOLAR:
    {ONTOLOGIA_AISA}
    """)
    return {"messages": [llm.invoke([prompt_sistema] + state["messages"])]}

graph_builder.add_node("chatbot", chatbot_node)
graph_builder.add_node("tools", ToolNode([enviar_whatsapp_humano]))
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

jarvi_graph = graph_builder.compile(checkpointer=memory)

# =====================================================================
# 6. TÍTULO E INSTRUCCIONES (UI)
# =====================================================================
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""
    ¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**. Para obtener la mejor asesoría, realizaremos estos pasos:
    * **1. Descubrimiento:** Identificamos tus necesidades reales.
    * **2. Análisis Técnico:** Calculamos tu consumo y requerimientos.
    * **3. Especificación:** Seleccionamos los mejores equipos de [AISA](https://www.aisa.com.gt).
    * **4. Presupuesto:** Generamos una propuesta validada técnicamente en GTQ.
    * **5. Contacto directo:** Tras definir tu solución, te trasladaré vía WhatsApp con el equipo humano de AISA.
    """)

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    greeting = "¡Hola! 👋 Soy Jarvi, Ingeniero de Soluciones de AISA Solar. Para iniciar a definir tus necesidades, ¿podrías indicarme tu Nombre y tu número de WhatsApp?"
    st.session_state.messages = [AIMessage(content=greeting)]
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    jarvi_graph.update_state(config, {"messages": [AIMessage(content=greeting)]})

# Renderizado del historial
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage): st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage): st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage): st.chat_message("system").markdown(f"⚙️ Operación: {msg.content}")

if prompt := st.chat_input("¿Qué solución necesitas hoy: paneles, bombeo o respaldo? Cuéntame ubicación, consumo y si buscas ahorro, autonomía o continuidad."):
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Consultando en tiempo real con nuestro equipo de ingeniería especializada..."):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=prompt)]}, config)
            
            # Actualizar historial
            new_messages = response_state["messages"][len(st.session_state.messages)-1:]
            for msg in new_messages:
                if isinstance(msg, AIMessage) and msg.content:
                    st.markdown(msg.content)
                elif isinstance(msg, ToolMessage):
                    st.markdown(f"⚙️ {msg.content}")
            
            st.session_state.messages = response_state["messages"]
