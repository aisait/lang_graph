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
    "PANELES": """ENERGÍA SOLAR (CAPTACIÓN FOTOVOLTAICA Y SISTEMAS ON-GRID)
5 — https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7 (inversor grid‑tie monofásico, microinversor solar, sistema fotovoltaico interconectado, medidor bidireccional, inyección a red BT)
11 — https://www.aisa.com.gt/shop/category/paneles-solares-18 (panel solar 150W 12V policristalino, módulo fotovoltaico 330W 24V, panel solar monocristalino PERC, célula solar 5BB, panel solar tipo marco de aluminio)
29 — https://www.aisa.com.gt/shop/category/consumo-basico-on-grid-28 (kit solar básico 1kW on‑grid, 2 paneles 330W + microinversor, sistema interconectado económico, ahorro en factura eléctrica, monitoreo vía web)
30 — https://www.aisa.com.gt/shop/category/consumo-intermedio-on-grid-29 (kit solar 2.5kW grid‑tie, 6 paneles monocristalinos 400W, inversor string monofásico, estructura de techo inclinado, conexión a tablero principal)
31 — https://www.aisa.com.gt/shop/category/instalacion-paneles-solares-33 (instalación llave en mano, montaje de paneles en techo, obra civil solar, ingeniería de sistemas fotovoltaicos, trámite de interconexión con EEGSA)
44 — https://www.aisa.com.gt/shop/category/consumo-alto-on-grid-46 (kit solar 5kW on‑grid, 12 paneles 450W, inversor string de 5kW, optimizadores de potencia, inyección total a red BT)
59 — https://www.aisa.com.gt/shop/category/consumo-comercial-alto-on-grid-89 (kit solar comercial 10kW, 24 paneles 450W, inversor trifásico 10kW, estructura coplanar, analizador de energía)
60 — https://www.aisa.com.gt/shop/category/consumo-comercial-industrial-on-grid-90 (sistema solar industrial 30kW, inversor centralizado, transformador BT/MT, monitorización SCADA, 80 paneles 550W)
61 — https://www.aisa.com.gt/shop/category/consumo-comercial-intermedio-on-grid-88 (kit solar 3kW negocio, 8 paneles 400W, inversor monofásico 3kW, kit anclaje techo plano, medidor de generación)
76 — https://www.aisa.com.gt/shop/category/consumo-comercial-basico-on-grid-91 (kit solar negocio pequeño 1.5kW, 4 paneles 400W, inversor monofásico, kit estructura para techo liviano, retorno inversión acelerado)""",

    "INVERSORES": """CONVERSIÓN ENERGÉTICA (INVERSORES Y TRANSFORMADORES)
26 — https://www.aisa.com.gt/shop/category/inversores-22 (inversor de onda senoidal pura 1000W, inversor cargador 24V, inversor de voltaje 12V a 110V, protección de bajo voltaje, inversor con display LCD)
28 — https://www.aisa.com.gt/shop/category/serie-smart-27 (inversor inteligente WiFi, monitorización remota app, controlador solar con Bluetooth, inversor smart grid interactivo, protección anti isla integrada)
41 — https://www.aisa.com.gt/shop/category/inv-ongrid-42 (inversor on‑grid 3kW 220V, eficiencia europea 97%, comunicación RS485, inversor sin transformador, refrigeración por convección natural)
42 — https://www.aisa.com.gt/shop/category/inv-car-43 (inversor para coche 150W, onda modificada con USB, encendedor de cigarro, protección bajo voltaje batería auto, inversor portátil para laptop)
43 — https://www.aisa.com.gt/shop/category/inv-pro-44 (inversor senoidal puro 2000W 24V, conexión a banco de baterías, ventilación forzada inteligente, protección cortocircuito, arranque de motor inducción)
62 — https://www.aisa.com.gt/shop/category/inversor-hibrido-67 (inversor híbrido 5kW 48V, entrada para generador, carga de baterías programable, salida 110/220V, pantalla táctil)
71 — https://www.aisa.com.gt/shop/category/inv-ongrid-trifasico-77 (inversor trifásico 15kW 400V, salida 380V 60Hz, comunicación Modbus, topología sin transformador, seguidor MPP dual)""",

    "CONTROLADORES": """CONTROL Y GESTIÓN DE ENERGÍA
38 — https://www.aisa.com.gt/shop/category/controlador-mppt-39 (controlador MPPT 40A 12/24V, seguimiento punto máximo potencia, eficiencia 99%, display LCD programable, protección sobrecarga solar)
39 — https://www.aisa.com.gt/shop/category/controlador-pwm-40 (controlador PWM 10A 12V, carga por modulación de ancho de pulso, indicador LED bicolor, compensación temperatura, salida USB 5V)
72 — https://www.aisa.com.gt/shop/category/controladores-bombas-82 (controlador de nivel de agua, relé flotador electrónico, variador de frecuencia para bomba, protector contra marcha en seco, arrancador suave 1HP)
73 — https://www.aisa.com.gt/shop/category/flotadores-84 (flotador interruptor 10A, boya de nivel con contrapeso, flotador de mercurio, pera flotante para tanque, cable flotador 2 metros)""",

    "BATERIAS": """ALMACENAMIENTO ENERGÉTICO
14 — https://www.aisa.com.gt/shop/category/baterias-solares-21 (batería solar 12V 100Ah AGM, batería estacionaria de plomo‑ácido, acumulador de ciclo profundo OPzS, batería para sistema solar aislado, vida útil 800 ciclos)
15 — https://www.aisa.com.gt/shop/category/baterias-solares-bateria-de-gel-26 (batería de gel 12V 65Ah, batería gel VRLA profunda, electrolito gelificado tixotrópico, batería sin emisión de gases, batería solar gel libre mantenimiento)
16 — https://www.aisa.com.gt/shop/category/baterias-solares-bateria-para-ups-97 (batería para UPS 12V 9Ah, batería de respaldo monoblock AGM, batería para SAI de computadora, batería de gel para UPS online, respaldo para central telefónica)
17 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-acido-plomo-liquido-104 (batería de plomo‑ácido con vasos transparentes, batería de electrolito líquido 12V 150Ah, batería de celdas inundadas, mantenimiento con agua destilada, batería tipo tracción semiabierta)
18 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-backup-105 (batería backup 12V 200Ah AGM, acumulador de respaldo para hogar, batería de emergencia sin derrames, banco de baterías para inversor de respaldo, soporte de carga profunda)
19 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-hibridos-y-aislados-106 (batería para sistema híbrido 48V, batería de litio LiFePO4 5kWh, batería de alta descarga para off‑grid, batería compatible con inversor híbrido, celda prismática de litio)
20 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-telecomunicaciones-107 (batería para repetidor 48V, batería de gel telecom, batería estacionaria para radio base, resistencia a descargas largas, batería para gabinete outdoor)
21 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-de-alarma-108 (batería alarma 12V 7Ah AGM, batería para central de incendios, acumulador sellado para sensor, respaldo para sirena inalámbrica, batería de plomo‑ácido 12V 4.5Ah)
22 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-de-videovigilancia-109 (batería para cámara 12V 12Ah, respaldo para DVR, batería gel para CCTV exterior, acumulador para grabación continua, fuente de poder con batería integrada)
23 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-kits-de-iluminacion-110 (batería 6V 4.5Ah para linterna, acumulador de lámpara solar recargable, pack de baterías AA NiMH, batería para lámpara de emergencia LED, pila recargable para reflector solar)
24 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-vehiculos-electricos-111 (batería de litio 48V para scooter, pack de iones de litio 60V, batería para bicicleta eléctrica, celda cilíndrica 18650, cargador de batería para moto eléctrica)
25 — https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-otros-usos-112 (batería para pesca eléctrica 12V 35Ah, acumulador para equipo médico portátil, batería de juguete eléctrico, fuente de alimentación DC para campamento, batería AGM de uso general 12V)""",

    "BOMBEO": """BOMBEO SOLAR (CAPTACIÓN Y APLICACIÓN HIDRÁULICA)
6 — https://www.aisa.com.gt/shop/category/bombas-perifericas-8 (bomba periférica 0.5 HP, bomba autocebante de superficie, bomba centrífuga monofásica 110V, bomba presurizadora para tanque, turbina periférica silenciosa)
7 — https://www.aisa.com.gt/shop/category/bombas-sumergibles-bajo-caudal-9 (bomba sumergible 4" baja potencia, bomba de pozo profundo 0.5 HP, bomba sumergible 12V DC, bomba de diafragma solar, bomba sumergible para riego por goteo)
32 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-34 (bomba recirculadora silenciosa 110V, bomba de rotor húmedo para calentador solar, impulsor de latón, bajo consumo 25W, circulación forzada de agua caliente)
33 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-bombas-de-recirculacion-individuales-93 (bomba recirculadora individual 3 velocidades, cuerpo en hierro fundido, conexión roscada ½", temporizador integrado, recirculación para calefón solar)
34 — https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-sistemas-bomba-de-recirculacion-94 (kit recirculación solar con controlador, sistema de lazo cerrado, válvula de retorno termostática, estación de bombeo solar, control diferencial de temperatura)
35 — https://www.aisa.com.gt/shop/category/bomba-presurizadora-35 (bomba presurizadora automática ½ HP, tanque de presión hidroneumático, sensor de flujo, arranque por demanda, bomba booster para ducha)
50 — https://www.aisa.com.gt/shop/category/bomba-caudal-no-sumergible-54 (bomba centrífuga 1HP 110V, motobomba gasolina 2", bomba jet autocebante, bomba de riego monoblock, impulsor de hierro)
51 — https://www.aisa.com.gt/shop/category/sistemas-bombas-sumergibles-56 (kit bomba sumergible solar 1HP, panel solar 300W, controlador bomba MPPT, tubería de polietileno, boya de nivel automática)
52 — https://www.aisa.com.gt/shop/category/sistemas-de-bombas-perifericas-57 (sistema bombeo periférico solar, bomba 0.5HP DC, módulo 150W, soporte panel inclinado, regulador de presión)
53 — https://www.aisa.com.gt/shop/category/sistema-bomba-caudal-sumergible-alto-d-59 (bomba sumergible alta caudal 2HP, trituradora, impulsor vortex, descarga 3", sistema solar para achique de pozo séptico)
54 — https://www.aisa.com.gt/shop/category/sistema-bombas-de-caudal-no-sumergible-60 (kit riego solar superficial, motobomba 2HP 24V, bomba centrífuga acoplada, control por flotador, manguera de succión 2")
64 — https://www.aisa.com.gt/shop/category/sistema-bomba-caudal-sumergible-alto-69 (bomba sumergible 3HP 4", panel solar 600W, controlador de pozo, cable sumergible 10 AWG, tubería de impulsión galvanizada)
77 — https://www.aisa.com.gt/shop/category/bombas-de-caudal-sumergible-desechos-92 (bomba fecal 1HP, impulsor turbina abierta, paso de sólidos 2", bomba trituradora WC, drenaje para aguas negras)
78 — https://www.aisa.com.gt/shop/category/bombas-sumergibles-alto-caudal-95 (bomba sumergible 5HP 8", motor encapsulado, alto caudal 500L/min, carcasa de acero inoxidable, impulsor tipo turbina)""",

    "CALENTAMIENTO": """CALENTAMIENTO SOLAR TÉRMICO
1 — https://www.aisa.com.gt/shop/category/calentadores-solares-1 (colector solar térmico plano, termotanque solar presurizado, calentador solar de tubos al vacío, sistema termosifónico solar, calentador solar no presurizado)
8 — https://www.aisa.com.gt/shop/category/bombas-de-calor-10 (bomba de calor aire‑agua, bomba de calor para piscina inverter, sistema aerotérmico residencial, compresor scroll de alta eficiencia, calentador termodinámico)
12 — https://www.aisa.com.gt/shop/category/resistencias-para-calentadores-19 (resistencia blindada 1500W 110V, resistencia de inmersión para termotanque, resistencia de repuesto para ducha eléctrica, termostato de seguridad, resistencia roscada 1½")
27 — https://www.aisa.com.gt/shop/category/calentadores-solares-deluxe-25 (calentador solar presurizado doble tanque, colector selectivo de titanio, intercambiador de calor de cobre, calentador solar con serpentín, calentador de acero inoxidable premium)
40 — https://www.aisa.com.gt/shop/category/repuesto-de-calentador-41 (ánodo de magnesio, empaque de tapa, termostato de repuesto, válvula de alivio de presión, tubos de vacío de repuesto)
65 — https://www.aisa.com.gt/shop/category/all-calentadores-70 (calentador solar catalogo completo, calentador tubos vacío 200L, calentador presurizado 300L, calefón solar económico, termo solar con respaldo eléctrico)
70 — https://www.aisa.com.gt/shop/category/marcos-de-calentadores-75 (marco calentador solar 15 tubos, soporte de acero galvanizado, base para termotanque horizontal, patas ajustables, kit de anclaje a losa)""",

    "REFRIGERACION": """REFRIGERACIÓN Y CLIMATIZACIÓN
9 — https://www.aisa.com.gt/shop/category/refrigeracion-solar-14 (refrigerador solar 12/24V DC, nevera congelador para cabaña, congelador de corriente directa, refrigerador solar portátil, nevera tipo arcón solar)
37 — https://www.aisa.com.gt/shop/category/congelador-38 (congelador arcón 7 pies 110V, congelador horizontal blanco, control de temperatura mecánico, tapa con bisagra, enfriamiento por compresor)
57 — https://www.aisa.com.gt/shop/category/congelador-solar-64 (congelador 12/24V 100 litros, arcón solar DC, compresor Danfoss, freezer para vacunas, bajo consumo diario 0.5kWh)
58 — https://www.aisa.com.gt/shop/category/refrigerador-65 (refrigerador 110V 12 pies, nevera frost, control electrónico, puerta reversible, refrigerante R600a)
63 — https://www.aisa.com.gt/shop/category/compresor-68 (compresor rotativo 1HP R410a, compresor hermético para nevera, motor monofásico 110V, pie para base, kit de arranque PTC)
74 — https://www.aisa.com.gt/shop/category/ice-maker-85 (máquina hielo 23kg/día, fabricador de cubitos, bandeja antiadherente, producción ciclo rápido, depósito de hielo integrado)
75 — https://www.aisa.com.gt/shop/category/ice-maker-maquinas-de-granizados-115 (raspadora de hielo industrial, granizadora 110V, cuchilla de acero inoxidable, tolva de policarbonato, dispensador de granizado)
86 — https://www.aisa.com.gt/shop/category/hielera-portatil-122 (hielera eléctrica 12V 15L, nevera portátil compresor, enfriador termoeléctrico, hielera camping 24 litros, asa y ruedas integradas)""",

    "ACCESORIOS": """CABLES, PROTECCIONES Y ACCESORIOS
2 — https://www.aisa.com.gt/shop/category/tuberia-4 (tubería PVC cédula 40, tubo CPVC para agua caliente, poliducto corrugado eléctrico, tubería PEX flexible, manguera reforzada para bomba)
3 — https://www.aisa.com.gt/shop/category/accesorios-5 (codo PVC 90° presión, tee PVC lisa, unión universal roscable, válvula de bola PVC, adaptador macho hembra PVC)
4 — https://www.aisa.com.gt/shop/category/iluminacion-dc-6 (foco LED 12V E27, lámpara solar recargable DC, tira LED 24V flexible, reflector LED bajo consumo 12V, bombilla DC para panel solar)
13 — https://www.aisa.com.gt/shop/category/turbinas-eolicas-20 (aerogenerador 400W 12V, turbina eólica de eje horizontal, controlador de carga eólico, aspas de fibra de vidrio, generador eólico con freno electromagnético)
36 — https://www.aisa.com.gt/shop/category/bombilla-36 (bombilla LED E27 9W, foco ahorrador rosca gruesa, luz cálida 3000K, LED SMD2835, iluminación interior de larga duración)
49 — https://www.aisa.com.gt/shop/category/repuestos-y-herrajes-52 (soporte panel solar teja, perfil de aluminio triangular, grapa intermedia panel, tornillo de tierra M8, abrazadera omega para riel)
55 — https://www.aisa.com.gt/shop/category/flipones-61 (breaker termomagnético 15A, interruptor diferencial, protector de sobrecarga, flipón enchufable 20A, disyuntor 2 polos 30A)
56 — https://www.aisa.com.gt/shop/category/conectores-mc4-62 (conector MC4 macho, conector MC4 hembra, par de conectores 30A, herramienta crimpadora MC4, tapa impermeable IP67)
66 — https://www.aisa.com.gt/shop/category/tanques-71 (tanque rotoplas 1100 litros, cisterna plástica tricapa, tinaco vertical, filtro de entrada, tanque de polietileno de alta densidad)
80 — https://www.aisa.com.gt/shop/category/cables-99 (cable THHN 12 AWG, cable encauchetado 3x12, alambre de cobre desnudo, cable uso rudo 3x10, cordón dúplex 2x16)
81 — https://www.aisa.com.gt/shop/category/cables-cable-solar-37 (cable solar 6mm² 1.5kV, aislamiento XLPE, doble capa UV, cable negro y rojo, certificación TÜV)
82 — https://www.aisa.com.gt/shop/category/cables-cable-bateria-100 (cable batería 2/0 AWG, extraflexible clase M, aislamiento PVC 60V, terminal estañado, color rojo y negro)
83 — https://www.aisa.com.gt/shop/category/cables-cable-sumergible-101 (cable sumergible 4 hilos 10 AWG, aislamiento EPDM, cubierta de polietileno, apto agua potable, cable bomba 200 metros)
84 — https://www.aisa.com.gt/shop/category/cables-tsj-102 (cable TSJ 3x14, cordón extraflexible, servicio severo, 300V, chaqueta de PVC resistente a la abrasión)
85 — https://www.aisa.com.gt/shop/category/cables-kit-cable-103 (kit cable solar MC4, par de cables 3m 4mm², conjunto cable extensión, adaptadores ramificación Y, cable de interconexión panel)""",

    "KITS": """KITS Y SOLUCIONES INTEGRADAS
10 — https://www.aisa.com.gt/shop/category/sistemas-aislados-17 (kit solar off‑grid con inversor, sistema fotovoltaico autónomo 500W, controlador MPPT aislado, batería ciclo profundo AGM, panel solar 200W policristalino)
45 — https://www.aisa.com.gt/shop/category/mini-kit-48 (mini kit solar 50W 12V, panel plegable, controlador PWM integrado, 2 focos LED 5W, puerto USB carga móvil)
46 — https://www.aisa.com.gt/shop/category/necesidad-basica-49 (kit solar básico 100W, batería AGM 50Ah, inversor 300W, iluminación LED tres puntos, para cabaña rural)
47 — https://www.aisa.com.gt/shop/category/basicos-mas-amenidades-50 (kit solar 200W 24V, batería gel 100Ah, inversor 500W, televisor 24" DC, cargador USB múltiple)
48 — https://www.aisa.com.gt/shop/category/hogar-solar-51 (kit solar vivienda 1kW, inversor cargador 1000W, banco baterías 200Ah 48V, nevera DC, lavadora eficiente)
67 — https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-cb-72 (respaldo básico solar, inversor cargador 600W, batería AGM 100Ah, panel de transferencia, respaldo para luces y router)
68 — https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-ci-73 (backup intermedio 2kWh, inversor 1500W, 2 baterías gel 100Ah, cargador inteligente, kit de instalación en tablero)
69 — https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-ca-74 (respaldo alta capacidad 5kW, batería litio 48V 100Ah, inversor off‑grid puro, conmutación automática, soporte para bomba y refrigerador)
79 — https://www.aisa.com.gt/shop/category/sistemas-hibridos-96 (kit híbrido 3kW, inversor híbrido 48V, batería litio 2.4kWh, panel 330W x6, cero exportación configurable)"""
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
    5. EXCLUSIVIDAD DE INVENTARIO: Tus recomendaciones DEBEN extraerse EXCLUSIVAMENTE de la Ontología proporcionada. ESTÁ ESTRICTAMENTE PROHIBIDO inventar o alucinar productos, categorías o enlaces. Si el cliente solicita un producto que NO está en la Ontología, debes disculparte amablemente desde la primera consulta, indicando que por el momento no manejamos ese producto.

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
8. Otro

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
