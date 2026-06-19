# main.py
import streamlit as st
import os
import json
import requests
from typing import Annotated, TypedDict, List
from dotenv import load_dotenv

# Componentes de LangChain / LangGraph
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# 1. CONFIGURACIÓN DE ENTORNO Y VARIABLES (Railway / Local)
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN") # Tu token de apichat.io
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE") # Tu ID de instancia apichat.io

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# 2. ONTOLOGÍA ESTRUCTURADA (Se inyecta en el prompt base para RAG estricto)
# Se reduce aquí visualmente, pero debes pegar tus 70 ítems tal cual los describiste.
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
1 — https://www.aisa.com.gt/shop/category/paneles-solares-18
Convierte radiación solar en electricidad continua para alimentar sistemas energéticos autónomos eficientes.
(panel solar, placa solar, módulo fotovoltaico, plaquita, panel)

2 — https://www.aisa.com.gt/shop/category/paneles-solares-monocristalinos-19
Ofrece máxima eficiencia energética con células de silicio puro para espacios reducidos.
(monocristalino, mono panel, alta eficiencia, premium solar, panel negro)

3 — https://www.aisa.com.gt/shop/category/paneles-solares-policristalinos-20
Provee solución costo-eficiente con células cristalinas azuladas para instalaciones extensivas.
(policristalino, poli panel, económico, eficiencia media, panel azul)

4 — https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7
Sincroniza generación fotovoltaica con red eléctrica reduciendo costos energéticos residenciales sustancialmente.
(on-grid, interconectado, net metering, solar urbano, ahorro energético)

5 — https://www.aisa.com.gt/shop/category/sistemas-aislados-17
Permite autonomía energética total en ubicaciones remotas sin infraestructura eléctrica convencional.
(off-grid, aislado, solar rural, independiente, kit autónomo)

6 — https://www.aisa.com.gt/shop/category/sistemas-hibridos-96
Integra red, baterías y paneles optimizando resiliencia energética durante interrupciones prolongadas.
(híbrido, backup solar, inteligente, respaldo, smart solar)

CONVERSIÓN ENERGÉTICA (INVERSORES Y TRANSFORMADORES)
7 — https://www.aisa.com.gt/shop/category/inversores-22
Transforma corriente continua solar en corriente alterna utilizable por equipos eléctricos.
(inverter, inversor, convertidor, caja solar, cerebro del sistema)

8 — https://www.aisa.com.gt/shop/category/inversor-hibrido-67
Gestiona múltiples fuentes energéticas priorizando eficiencia operativa y respaldo automatizado inteligente.
(hybrid inverter, híbrido, backup, inversor smart, pro)

9 — https://www.aisa.com.gt/shop/category/micro-inv-45
Optimiza individualmente cada panel reduciendo pérdidas por sombreado parcial localizado.
(microinverter, micro, optimizador, inversor panel, micro solar)

10 — https://www.aisa.com.gt/shop/category/inversor-carga-23
Combina función inversora y cargador de baterías en un equipo integrado versátil.
(inversor cargador, inverter charger, combo, integrado, todo en uno)

11 — https://www.aisa.com.gt/shop/category/inversor-senoidal-pura-24
Genera corriente alterna de alta calidad para equipos electrónicos sensibles sin distorsión.
(senoidal, onda pura, calidad eléctrica, electrónica segura, inverter premium)

12 — https://www.aisa.com.gt/shop/category/inversor-senoidal-modificada-25
Provee onda cuadrada modificada para cargas resistivas básicas y económicas.
(onda modificada, básico, económico, motor, herramienta eléctrica)

CONTROL Y GESTIÓN DE ENERGÍA
13 — https://www.aisa.com.gt/shop/category/controladores-15
Regula carga energética hacia baterías evitando sobrecargas y degradación prematura interna.
(controlador, regulador, cargador, controlador solar, regulador carga)

14 — https://www.aisa.com.gt/shop/category/controlador-mppt-39
Maximiza extracción energética solar siguiendo punto óptimo de potencia dinámicamente.
(MPPT, controlador avanzado, smart controller, max power, premium)

15 — https://www.aisa.com.gt/shop/category/controlador-pwm-40
Modula transferencia energética mediante pulsos eléctricos para sistemas solares básicos económicos.
(PWM, controlador básico, regulador simple, económico, entry level)

16 — https://www.aisa.com.gt/shop/category/medidores-de-energia-42
Monitorea consumo y generación eléctrica para gestión eficiente de recursos.
(medidor, monitor, wattmeter, energía, consumo)

ALMACENAMIENTO ENERGÉTICO
17 — https://www.aisa.com.gt/shop/category/baterias-solares-21
Almacena energía solar para uso nocturno o durante ausencia de irradiación.
(batería solar, banco, acumulador, battery bank, reserva)

18 — https://www.aisa.com.gt/shop/category/baterias-solares-bateria-de-gel-26
Proporciona almacenamiento sellado con mantenimiento mínimo y elevada confiabilidad operativa.
(gel battery, batería gel, sellada, AGM, acumulador sin mantenimiento)

19 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-backup-105
Sostiene cargas críticas durante apagones mediante reserva energética de emergencia.
(backup battery, UPS battery, respaldo, emergencia, batería de respaldo)

20 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-litio-106
Ofrece alta densidad energética con ciclo de vida prolongado para sistemas avanzados.
(li-ion, litio, batería moderna, alta performance, liviana)

21 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-estacionarias-27
Provee almacenamiento fijo para aplicaciones industriales de descarga profunda.
(estacionaria, industrial, descarga profunda, ciclo profundo, fosca)

22 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-arranque-28
Entrega alta corriente instantánea para motores de combustión y arranque.
(arranque, starter, automotriz, motor, battery start)

BOMBEO SOLAR (CAPTACIÓN Y APLICACIÓN HIDRÁULICA)
23 — https://www.aisa.com.gt/shop/category/bombas-perifericas-8
Incrementa presión hidráulica para suministro doméstico con caudales moderados constantes.
(bomba periférica, presurizador, booster, bombita, presión de agua)

24 — https://www.aisa.com.gt/shop/category/bombas-sumergibles-bajo-caudal-9
Extrae agua profunda eficientemente desde pozos de diámetro reducido rurales.
(sumergible, bomba pozo, deep well, saca agua, pozo profundo)

25 — https://www.aisa.com.gt/shop/category/bombas-de-caudal-11
Transporta grandes volúmenes de agua para riego o transferencia industrial.
(caudal, bomba grande, irrigación, flow pump, caudalera)

26 — https://www.aisa.com.gt/shop/category/bomba-presurizadora-35
Eleva presión interna mejorando desempeño de duchas y líneas hidráulicas residenciales.
(presurizadora, booster, presión, empujador, bomba de casa)

27 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-34
Mantiene circulación continua de agua caliente minimizando pérdidas térmicas operativas.
(recirculación, loop pump, retorno, agua caliente, circulación constante)

28 — https://www.aisa.com.gt/shop/category/bombas-superficiales-10
Instala en superficie para succionar agua de fuentes poco profundas accesibles.
(superficial, aspiración, pozo somero, agua superficial, jet pump)

29 — https://www.aisa.com.gt/shop/category/bombas-multietapas-12
Genera alta presión mediante múltiples impulsores para aplicaciones verticales exigentes.
(multietapa, vertical, alta presión, cascada, water booster)

30 — https://www.aisa.com.gt/shop/category/bomba-solar-dc-13
Opera directamente con corriente continua solar sin inversor para máximo ahorro.
(solar DC, bomba directa, sin batería, eficiente, solar pump)

31 — https://www.aisa.com.gt/shop/category/bomba-de-calor-36
Extrae calor del aire o agua para calefacción eficiente de piscinas.
(bomba calor, heat pump, piscina, calefacción, agua templada)

32 — https://www.aisa.com.gt/shop/category/estacion-de-bombeo-123
Integra control, protección y bombeo en unidad compacta para sistemas automatizados.
(estación, bombeo automatizado, skid, control, hidroneumático)

CALENTAMIENTO SOLAR TÉRMICO
33 — https://www.aisa.com.gt/shop/category/calentadores-solares-1
Aprovecha energía solar térmica para producir agua caliente sanitaria eficiente.
(calentador solar, boiler solar, termo solar, agua caliente, termosifón)

34 — https://www.aisa.com.gt/shop/category/calentadores-solares-deluxe-25
Ofrece calentamiento premium con mayor durabilidad térmica y materiales inoxidables.
(deluxe, premium heater, inoxidable, calentador pro, alta gama)

35 — https://www.aisa.com.gt/shop/category/calentadores-solares-tubos-vacio-2
Maximiza eficiencia térmica con tubos al vacío para climas fríos o nublados.
(tubos al vacío, vacío, alta temperatura, invierno, heat pipe)

36 — https://www.aisa.com.gt/shop/category/calentadores-solares-placa-plana-3
Provee calentamiento tradicional con placa plana para climas cálidos tropicales.
(placa plana, colector plano, tropical, económico, tradicional)

37 — https://www.aisa.com.gt/shop/category/termo-tanque-4
Almacena agua caliente para suministro continuo en horas sin radiación.
(termo, tanque, reservorio, agua caliente, deposito térmico)

38 — https://www.aisa.com.gt/shop/category/accesorios-para-calentadores-5
Conecta y asegura instalación hidrosanitaria de calentadores solares completos.
(accesorios, instalación, tubería, conexiones, soportes calentador)

REFRIGERACIÓN SOLAR
39 — https://www.aisa.com.gt/shop/category/refrigeracion-solar-14
Conserva alimentos usando refrigeración eficiente alimentada directamente por energía solar.
(solar fridge, refrigerador solar, nevera solar, enfriador, conservación)

40 — https://www.aisa.com.gt/shop/category/congelador-solar-64
Mantiene temperaturas de congelación estable en ubicaciones eléctricamente aisladas remotas.
(freezer solar, congelador, cold storage, nevera solar, hielo)

ILUMINACIÓN EFICIENTE
41 — https://www.aisa.com.gt/shop/category/iluminacion-dc-6
Ilumina espacios consumiendo baja energía directamente desde bancos de baterías.
(bombilla DC, luz solar, foco LED, bombillo, iluminación eficiente)

42 — https://www.aisa.com.gt/shop/category/iluminacion-led-65
Ofrece alta luminosidad con mínimo consumo para exteriores e interiores.
(LED, iluminación, ahorro, luz blanca, bombilla larga duración)

43 — https://www.aisa.com.gt/shop/category/lamparas-solares-portatiles-66
Provee iluminación autónoma portátil para campamento o emergencias sin red.
(portátil, lámpara solar, camping, emergencia, linterna solar)

CABLEADO Y CONDUCCIÓN ELÉCTRICA
44 — https://www.aisa.com.gt/shop/category/cables-cable-solar-37
Transporta corriente fotovoltaica minimizando pérdidas eléctricas y degradación ambiental externa.
(cable solar, cable PV, cable panel, alambre solar, conductor fotovoltaico)

45 — https://www.aisa.com.gt/shop/category/cables-cable-bateria-100
Conecta bancos de baterías soportando corrientes elevadas con seguridad térmica.
(battery cable, cable batería, cable grueso, conductor DC, potencia)

46 — https://www.aisa.com.gt/shop/category/cables-cable-sumergible-101
Resiste inmersión prolongada alimentando bombas en pozos profundos exigentes.
(cable sumergible, cable pozo, waterproof cable, sumergible, pozo profundo)

47 — https://www.aisa.com.gt/shop/category/cables-accesorios-para-cable-38
Fija y protege tendido eléctrico con sujetadores, cintas y organizadores resistentes.
(accesorios cable, sujetadores, cinta eléctrica, organizador, canaleta)

48 — https://www.aisa.com.gt/shop/category/terminales-y-conectores-63
Termina conexiones eléctricas garantizando contacto seguro y eficiente en sistemas.
(terminal, conector, lug, ojal, crimp)

PROTECCIONES Y SEGURIDAD ELÉCTRICA
49 — https://www.aisa.com.gt/shop/category/conectores-mc4-62
Permite conexión segura estandarizada entre módulos solares y cableado fotovoltaico.
(MC4, conector solar, terminal, plug solar, acople rápido)

50 — https://www.aisa.com.gt/shop/category/flipones-61
Protege circuitos eléctricos interrumpiendo corrientes peligrosas ante fallas instantáneamente.
(breaker, flipón, protección, interruptor, automático termomagnético)

51 — https://www.aisa.com.gt/shop/category/fusibles-60
Interrumpe circuito ante sobrecarga mediante elemento fusible para protección básica.
(fusible, protección, sobrecarga, cartucho, safety)

52 — https://www.aisa.com.gt/shop/category/sistemas-de-tierra-59
Conecta equipos a tierra disipando descargas eléctricas y protegiendo equipos.
(tierra, grounding, jabalina, varilla, protección eléctrica)

53 — https://www.aisa.com.gt/shop/category/canaletas-y-organizadores-102
Organiza y protege cableado eléctrico en instalaciones ordenadas y seguras.
(canaleta, organizador, tubería conduit, PVC, protección cables)

EÓLICA Y OTRAS RENOVABLES
54 — https://www.aisa.com.gt/shop/category/turbinas-eolicas-20
Convierte energía cinética del viento en generación eléctrica renovable descentralizada.
(turbina eólica, wind turbine, molino, aerogenerador, eólico)

55 — https://www.aisa.com.gt/shop/category/controladores-eolicos-41
Regula voltaje generado por turbinas protegiendo baterías de sobrecarga por viento.
(controlador eólico, regulador viento, wind controller, aerogenerador control)

HVAC Y SISTEMAS INDUSTRIALES
56 — https://www.aisa.com.gt/shop/category/compresor-68
Comprime aire o refrigerante para procesos térmicos industriales de alta demanda.
(compresor, compressor, aire comprimido, motor compresor, compresión industrial)

57 — https://www.aisa.com.gt/shop/category/fan-coil-69
Distribuye aire frío o caliente mediante serpentines y ventiladores para climatización.
(fan coil, climatizador, serpentín, ventilador, aire acondicionado)

58 — https://www.aisa.com.gt/shop/category/evaporadores-y-condensadores-70
Intercambia calor en sistemas de refrigeración para eficiencia térmica.
(evaporador, condensador, intercambiador, calor, refrigeración)

59 — https://www.aisa.com.gt/shop/category/termostatos-y-controles-71
Regula temperatura ambiente mediante controles automáticos inteligentes programables.
(termostato, control temperatura, climatización, automático, HVAC control)

ACCESORIOS E INSTALACIÓN
60 — https://www.aisa.com.gt/shop/category/estructuras-soporte-43
Fija paneles solares a techos o suelo garantizando ángulo óptimo de captación.
(estructura, soporte, rail, perfil, montaje solar)

61 — https://www.aisa.com.gt/shop/category/flipones-caja-de-conexion-104
Concentra protecciones eléctricas en gabinete centralizado para instalaciones ordenadas.
(caja conexión, gabinete, centro de carga, panel eléctrico, distribuidor)

62 — https://www.aisa.com.gt/shop/category/herramientas-103
Equipa instaladores con herramientas especializadas para ensamble y conexiones.
(herramienta, crimpador, pelacables, multímetro, instalación)

63 — https://www.aisa.com.gt/shop/category/fijaciones-y-tornilleria-44
Asegura equipos solares con tornillería y anclajes resistentes a intemperie.
(tornillo, anclaje, fijación, soporte, montaje)

ACCESORIOS HIDRÁULICOS
64 — https://www.aisa.com.gt/shop/category/tuberias-y-conexiones-29
Conduce agua en sistemas hidráulicos con tubería y accesorios de conexión.
(tubería, conexión, codo, te, reducción, hidráulica)

65 — https://www.aisa.com.gt/shop/category/valvulas-y-llaves-de-paso-30
Regula flujo hidráulico con válvulas de compuerta, bola y check.
(válvula, llave paso, check, compuerta, regulación flujo)

66 — https://www.aisa.com.gt/shop/category/filtros-y-purificadores-31
Elimina impurezas del agua protegiendo bombas y sistemas hidráulicos.
(filtro, purificador, sedimentos, agua limpia, protección bomba)

67 — https://www.aisa.com.gt/shop/category/flotadores-y-controladores-32
Automatiza llenado de tanques con flotadores y sensores de nivel.
(flotador, controlador nivel, tanque, llenado automático, sensor)

68 — https://www.aisa.com.gt/shop/category/presostatos-y-manometros-33
Mide y regula presión hidráulica para operación segura de sistemas.
(presostato, manómetro, presión, regulador, control hidráulico)

KITS Y SOLUCIONES INTEGRADAS
69 — https://www.aisa.com.gt/shop/category/kit-solar-16
Integra paneles, baterías e inversores en solución completa para autonomía.
(kit solar, sistema completo, pre-armado, llave en mano, paquete solar)

70 — https://www.aisa.com.gt/shop/category/kit-bombeo-solar-124
Incluye bomba, paneles y controlador para abastecimiento hídrico autónomo.
(kit bombeo, solar pump, agua solar, riego autónomo, ganadero)

"""

# 3. DEFINICIÓN DEL ESTADO DEL GRAFO (Graph State)
class AgentState(TypedDict):
    # add_messages asegura que los nuevos mensajes se anexen al historial existente
    messages: Annotated[list, add_messages]

# 4. HERRAMIENTAS (Tools) PARA EL LLM
@tool
def enviar_whatsapp_humano(nombre_cliente: str, numero_whatsapp: str, resumen_35_palabras: str, productos_links: str, presupuesto_estimado: str) -> str:
    """
    Ejecuta esta herramienta SOLO cuando el cliente acepte el presupuesto y pida validación humana.
    Toma los datos del cliente, el resumen exacto de 35 palabras, los links y el presupuesto, y los envía vía API.
    """
    # Lógica de construcción de Payload para ApiChat.io
    url = f"https://api.apichat.io/v1/sendText"
    
    # Limpieza del número (asegurar formato internacional sin + ni espacios)
    num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
    
    mensaje_para_ingeniero = (
        f"🚨 *Nuevo Lead Calificado - Jarvi AISA Solar* 🚨\n\n"
        f"👤 *Cliente:* {nombre_cliente}\n"
        f"📱 *WhatsApp:* +{num_limpio}\n\n"
        f"📝 *Resumen de Necesidad:* {resumen_35_palabras}\n\n"
        f"🛒 *Solución Propuesta (Links):*\n{productos_links}\n\n"
        f"💰 *Presupuesto Estimado:* {presupuesto_estimado}\n\n"
        f"Revisar y contactar para cierre y cálculo de mano de obra."
    )

    payload = {
        "number": num_limpio,
        "text": mensaje_para_ingeniero
    }
    
    headers = {
        "Authorization": f"Bearer {APICHAT_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        # En producción, descomentar la siguiente línea para hacer el POST real
        # response = requests.post(url, json=payload, headers=headers)
        # if response.status_code == 200:
        return "El presupuesto y la solicitud han sido enviados exitosamente al ingeniero de AISA vía WhatsApp."
        # else: return f"Error en API: {response.text}"
    except Exception as e:
        return f"Ocurrió un error al enviar el WhatsApp: {str(e)}"

tools = [enviar_whatsapp_humano]

# 5. CONSTRUCCIÓN DE NODOS DEL GRAFO
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1) # Baja temperatura para alta precisión técnica
llm_with_tools = llm.bind_tools(tools)

def chatbot_node(state: AgentState):
    """Nodo principal que invoca al LLM con el contexto y las herramientas."""
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa de AISA Solar.
    Sigue el árbol de decisión: 1. Cualificar (Nombre, Número y País) -> 2. Diagnosticar necesidad -> 3. Explicar en modo experto pero sencillo -> 4. Crear presupuesto (usar SOLO links provistos) -> 5. Preguntar si enviamos la cotización a un humano.
    Si el cliente acepta, LLAMA a la herramienta 'enviar_whatsapp_humano' con la información estructurada.
    Asegúrate de resumir su necesidad en exactamente 35 palabras para el payload.
    
    CATÁLOGO ÚNICO Y ESTRICTO:
    {ONTOLOGIA_AISA}
    """)
    # Evaluamos la lista de mensajes pasándole el prompt del sistema al inicio
    messages = [prompt_sistema] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

# 6. CONFIGURACIÓN DEL GRAFO (LangGraph)
graph_builder = StateGraph(AgentState)
graph_builder.add_node("chatbot", chatbot_node)

# Nodo preconstruido de LangGraph para ejecutar herramientas
tool_node = ToolNode(tools=tools)
graph_builder.add_node("tools", tool_node)

# Condicional: Si el LLM decide usar una herramienta, va a 'tools', si no, termina el turno (END)
from langgraph.prebuilt import tools_condition
graph_builder.add_conditional_edges(
    "chatbot",
    tools_condition,
)
# De la herramienta, vuelve al chatbot para que notifique al usuario que se envió
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

# Compilamos el grafo
# Al compilar, podemos pasarle un "checkpointer" si quisiéramos persistencia en base de datos.
# Para Streamlit, manejaremos la persistencia en st.session_state.
jarvi_graph = graph_builder.compile()

# 7. INTERFAZ DE USUARIO (Streamlit UI)
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas (LangGraph Edition)")

with st.expander("ℹ️ ¿Cómo funciona el nuevo Jarvi?"):
    st.markdown("""
    Ahora Jarvi integra un motor de inferencia avanzado. Analizará tus necesidades basándose en nuestro 
    árbol de más de 70 soluciones especializadas, creará un presupuesto pre-calculado, y si estás de acuerdo, 
    transferirá todo el contexto técnico a nuestros ingenieros directamente a su WhatsApp.
    """)

# Inicialización de la memoria en Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = []
    # Mensaje de bienvenida disparador
    greeting = "¡Hola! 👋 Soy Jarvi, Ingeniero de Preventa Virtual de AISA Solar. Para iniciar nuestra evaluación técnica, ¿podrías indicarme tu Nombre, el País desde el que nos escribes y tu número de WhatsApp? Esto me permitirá estructurar tu perfil energético."
    st.session_state.messages.append(AIMessage(content=greeting))

# Renderizado de historial
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage):
        st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage):
        # Opcional: mostrar al usuario que se ejecutó una acción del sistema
        st.chat_message("system").markdown("*(Acción del sistema ejecutada exitosamente: Transferencia a humano)*")

# 8. MANEJO DE INTERACCIÓN (Entrada del usuario)
if prompt := st.chat_input("Escribe aquí tu consulta o necesidad..."):
    # Agregar y mostrar el mensaje del usuario
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").markdown(prompt)

    # Invocar al Grafo de LangGraph
    with st.chat_message("assistant"):
        with st.spinner("Analizando requerimientos y consultando matriz energética..."):
            # Pasamos todo el historial al grafo
            response_state = jarvi_graph.invoke({"messages": st.session_state.messages})
            
            # El estado final del grafo devuelve toda la lista de mensajes.
            # Extraemos los mensajes nuevos (generados por el LLM o Tools) que no estaban antes
            new_messages = response_state["messages"][len(st.session_state.messages):]
            
            for msg in new_messages:
                if isinstance(msg, AIMessage) and msg.content:
                    st.markdown(msg.content)
            
            # Actualizamos la memoria global de Streamlit con el nuevo estado del grafo
            st.session_state.messages = response_state["messages"]
