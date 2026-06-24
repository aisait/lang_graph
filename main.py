import streamlit as st
import os
import requests
import uuid
import io
import json
import traceback
import datetime
import threading
import base64
import functools # Añadido para el modelo de auditoría
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Annotated, TypedDict, Optional
from dotenv import load_dotenv
from httpx import Client as HttpxClient
# Nuevas importaciones para Gmail API
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# IMPORTACIÓN Y CLIENTE PARA OPENAI (Whisper + TTS + Vision)
from openai import OpenAI

# =====================================================================
# MODELO DE AUDITORÍA TÉCNICA (SERVERLESS)
# =====================================================================
def auditar_fase(nombre_fase: str, criticidad: str = "ALTA"):
    """
    Decorador de auditoría para trazabilidad en arquitecturas serverless.
    Captura el contexto, variables y excepciones con formato ISO/Técnico.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Ejecución normal de la subfase
                return func(*args, **kwargs)
            except Exception as e:
                # Intercepción en tiempo de ejecución
                st.error(f"❌ Error Crítico Interceptado en Fase: {nombre_fase} (Criticidad: {criticidad})")
                tb_str = traceback.format_exc()
                timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                
                with st.expander("🛠️ Detalles Técnicos de Auditoría (Logs Serverless)", expanded=True):
                    st.markdown("### Contexto de Ejecución")
                    st.text(f"Timestamp (UTC): {timestamp_iso}")
                    st.text(f"Función Fallida: {func.__name__}")
                    
                    st.markdown("### Estado de Variables (Inputs)")
                    st.write(f"**Args posicionales:** {args}")
                    st.write(f"**Kwargs:** {kwargs}")
                    
                    st.markdown("### Trazado de Pila (Traceback)")
                    st.code(tb_str, language="python")
                
                raise e # Relanzamos para que LangGraph maneje el estado de memoria correctamente
        return wrapper
    return decorator

# =====================================================================
# 1. DEFINICIÓN DEL ESTADO (ACTUALIZADO - RUTEO EPISTEMOLÓGICO)
# =====================================================================
class InferenciaEnergetica(TypedDict):
    ciudad: Optional[str]
    empresa_electrica: Optional[str]
    tarifa_base_gtq: Optional[float]
    topologia: Optional[str]
    calculo_carga_completado: bool
    requiere_auditoria_electrica: bool 

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

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=HttpxClient(proxies=None) # Desactiva explícitamente el uso de proxies
)

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# =====================================================================
# HELPER GMAIL API (OAUTH2)
# =====================================================================
def enviar_correo_gmail_api(msg_multipart):
    """Envia correos utilizando la API de Gmail con Refresh Token"""
    creds = Credentials(
        token=None,
        refresh_token=os.getenv("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GMAIL_CLIENT_ID"),
        client_secret=os.getenv("GMAIL_CLIENT_SECRET")
    )
    try:
        service = build('gmail', 'v1', credentials=creds)
        raw_msg = base64.urlsafe_b64encode(msg_multipart.as_bytes()).decode('utf-8')
        service.users().messages().send(userId="me", body={'raw': raw_msg}).execute()
    except Exception as e:
        print(f"Error al enviar correo vía Gmail API: {e}")

# =====================================================================
# HELPER VISION API (ANÁLISIS DE FACTURA)
# =====================================================================
def procesar_imagen_factura(image_bytes):
    """Utiliza GPT-4o-mini para extraer datos estructurados de la fotografía de la factura"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analiza esta factura de electricidad de Guatemala. Extrae la siguiente información en formato JSON estricto: 1. 'empresa_electrica' (Busca EEGSA o ENERGUATE), 2. 'consumo_kwh' (sólo el número), 3. 'monto_factura' (sólo el número en Quetzales). Si no detectas un dato, asigna null."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

# =====================================================================
# 3. ONTOLOGÍA FRAGMENTADA (OPTIMIZACIÓN DE VENTANA DE CONTEXTO)
# =====================================================================
ONTOLOGIA_BLOQUES = {
    "1": {"nombre": "CALENTADORES SOLARES PARA AGUA CALIENTE RESIDENCIAL Y PISCINA", "url": "https://www.aisa.com.gt/shop/category/calentadores-solares-1", "keywords": ["colector solar térmico plano", "termotanque solar presurizado", "calentador solar de tubos al vacío", "sistema termosifónico solar", "calentador solar no presurizado"]},
    "2": {"nombre": "TUBERÍA Y CONDUCTOS PARA INSTALACIONES HIDROSANITARIAS Y SOLARES", "url": "https://www.aisa.com.gt/shop/category/tuberia-4", "keywords": ["tubería PVC cédula 40", "tubo CPVC agua caliente", "poliducto corrugado", "tubería PEX", "manguera reforzada"]},
    "3": {"nombre": "ACCESORIOS DE CONEXIÓN Y VÁLVULAS PARA TUBERÍA", "url": "https://www.aisa.com.gt/shop/category/accesorios-5", "keywords": ["codo PVC", "tee PVC", "unión universal", "válvula de bola PVC", "adaptador"]},
    "4": {"nombre": "ILUMINACIÓN LED DE CORRIENTE DIRECTA 12V Y 24V", "url": "https://www.aisa.com.gt/shop/category/iluminacion-dc-6", "keywords": ["foco LED 12V", "lámpara solar recargable", "tira LED 24V", "reflector LED"]},
    "5": {"nombre": "SISTEMAS SOLARES CONECTADOS A LA RED ELÉCTRICA ON‑GRID", "url": "https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7", "keywords": ["inversor grid-tie", "microinversor solar", "sistema fotovoltaico", "medidor bidireccional"]},
    "6": {"nombre": "BOMBAS PERIFÉRICAS PARA AGUA LIMPIA DE SUPERFICIE", "url": "https://www.aisa.com.gt/shop/category/bombas-perifericas-8", "keywords": ["bomba periférica", "bomba autocebante", "bomba centrífuga", "bomba presurizadora"]},
    "7": {"nombre": "BOMBAS SUMERGIBLES DE BAJO CAUDAL PARA POZOS ESTRECHOS", "url": "https://www.aisa.com.gt/shop/category/bombas-sumergibles-bajo-caudal-9", "keywords": ["bomba sumergible 4\"", "bomba pozo profundo", "bomba 12V DC", "bomba de diafragma"]},
    "8": {"nombre": "BOMBAS DE CALOR PARA CALEFACCIÓN Y AGUA CALIENTE EFICIENTES", "url": "https://www.aisa.com.gt/shop/category/bombas-de-calor-10", "keywords": ["bomba de calor aire-agua", "bomba de calor piscina", "aerotérmico"]},
    "9": {"nombre": "REFRIGERACIÓN SOLAR Y NEVERAS PARA SISTEMAS AISLADOS", "url": "https://www.aisa.com.gt/shop/category/refrigeracion-solar-14", "keywords": ["refrigerador solar 12/24V", "nevera congelador cabaña", "nevera solar"]},
    "10": {"nombre": "SISTEMAS SOLARES AISLADOS COMPLETOS CON BATERÍAS", "url": "https://www.aisa.com.gt/shop/category/sistemas-aislados-17", "keywords": ["kit solar off-grid", "sistema fotovoltaico autónomo", "batería ciclo profundo"]},
    "11": {"nombre": "PANELES SOLARES FOTOVOLTAICOS MONOCRISTALINOS Y POLICRISTALINOS", "url": "https://www.aisa.com.gt/shop/category/paneles-solares-18", "keywords": ["panel solar policristalino", "panel monocristalino", "módulo fotovoltaico"]},
    "12": {"nombre": "RESISTENCIAS ELÉCTRICAS PARA CALENTADORES SOLARES Y TERMODUCHAS", "url": "https://www.aisa.com.gt/shop/category/resistencias-para-calentadores-19", "keywords": ["resistencia blindada", "resistencia inmersión", "termostato"]},
    "13": {"nombre": "TURBINAS EÓLICAS DE PEQUEÑA POTENCIA PARA SISTEMAS HÍBRIDOS", "url": "https://www.aisa.com.gt/shop/category/turbinas-eolicas-20", "keywords": ["aerogenerador", "turbina eólica", "controlador eólico"]},
    "14": {"nombre": "BATERÍAS SOLARES ESTACIONARIAS DE CICLO PROFUNDO GENERAL", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-21", "keywords": ["batería solar AGM", "batería estacionaria", "acumulador ciclo profundo"]},
    "15": {"nombre": "BATERÍAS DE GEL SELLADAS LIBRES DE MANTENIMIENTO PARA SOLAR", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-bateria-de-gel-26", "keywords": ["batería de gel", "VRLA", "sin mantenimiento"]},
    "16": {"nombre": "BATERÍAS PARA UPS Y RESPALDO DE ENERGÍA ININTERRUMPIDA", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-bateria-para-ups-97", "keywords": ["batería UPS", "respaldo SAI"]},
    "17": {"nombre": "BATERÍAS DE ÁCIDO‑PLOMO LÍQUIDO ABIERTAS ECONÓMICAS", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-de-acido-plomo-liquido-104", "keywords": ["batería plomo-ácido", "electrolito líquido", "celdas inundadas"]},
    "18": {"nombre": "BATERÍAS PARA BACKUP Y SISTEMAS DE ENERGÍA DE EMERGENCIA", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-backup-105", "keywords": ["batería backup", "acumulador emergencia"]},
    "19": {"nombre": "BATERÍAS PARA SISTEMAS HÍBRIDOS Y AISLADOS CON INVERSOR", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-hibridos-y-aislados-106", "keywords": ["batería híbrida", "litio LiFePO4"]},
    "20": {"nombre": "BATERÍAS ESPECIALIZADAS PARA TELECOMUNICACIONES Y RADIOENLACES", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-telecomunicaciones-107", "keywords": ["batería telecom", "estacionaria radio base"]},
    "21": {"nombre": "BATERÍAS PARA SISTEMAS DE ALARMA Y SEGURIDAD RESIDENCIAL", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-de-alarma-108", "keywords": ["batería alarma", "acumulador seguridad"]},
    "22": {"nombre": "BATERÍAS PARA SISTEMAS DE VIDEOVIGILANCIA Y CÁMARAS IP", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-sistemas-de-videovigilancia-109", "keywords": ["batería cámara", "respaldo DVR"]},
    "23": {"nombre": "BATERÍAS PARA KITS DE ILUMINACIÓN PORTÁTIL Y LINTERNAS SOLARES", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-kits-de-iluminacion-110", "keywords": ["batería linterna", "pack baterías"]},
    "24": {"nombre": "BATERÍAS PARA VEHÍCULOS ELÉCTRICOS Y MOVILIDAD ELÉCTRICA LIVIANA", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-vehiculos-electricos-111", "keywords": ["batería litio scooter", "batería bicicleta eléctrica"]},
    "25": {"nombre": "BATERÍAS PARA USOS ESPECIALES, ENERGÍA PORTÁTIL Y OTROS EQUIPOS", "url": "https://www.aisa.com.gt/shop/category/baterias-solares-baterias-para-otros-usos-112", "keywords": ["batería equipo médico", "batería pesca"]},
    "26": {"nombre": "INVERSORES DE CORRIENTE PARA SISTEMAS SOLARES Y RESPALDO", "url": "https://www.aisa.com.gt/shop/category/inversores-22", "keywords": ["inversor onda pura", "inversor cargador"]},
    "27": {"nombre": "CALENTADORES SOLARES DELUXE DE ALTA EFICIENCIA Y DISEÑO PREMIUM", "url": "https://www.aisa.com.gt/shop/category/calentadores-solares-deluxe-25", "keywords": ["calentador presurizado premium", "serpentín"]},
    "28": {"nombre": "SERIE SMART DE INVERSORES Y CONTROL SOLAR INTELIGENTE", "url": "https://www.aisa.com.gt/shop/category/serie-smart-27", "keywords": ["inversor inteligente", "monitorización remota"]},
    "29": {"nombre": "KITS SOLARES ON‑GRID DE CONSUMO BÁSICO PARA HOGAR PEQUEÑO", "url": "https://www.aisa.com.gt/shop/category/consumo-basico-on-grid-28", "keywords": ["kit solar 1kW on-grid"]},
    "30": {"nombre": "SISTEMAS ON‑GRID DE CONSUMO INTERMEDIO PARA FAMILIAS MEDIANAS", "url": "https://www.aisa.com.gt/shop/category/consumo-intermedio-on-grid-29", "keywords": ["kit solar 2.5kW grid-tie"]},
    "31": {"nombre": "SERVICIO DE INSTALACIÓN PROFESIONAL DE PANELES SOLARES", "url": "https://www.aisa.com.gt/shop/category/instalacion-paneles-solares-33", "keywords": ["instalación llave en mano", "ingeniería fotovoltaica"]},
    "32": {"nombre": "BOMBAS DE RECIRCULACIÓN PARA SISTEMAS DE AGUA CALIENTE SOLAR", "url": "https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-34", "keywords": ["bomba recirculadora", "circulación forzada"]},
    "33": {"nombre": "UNIDADES INDIVIDUALES DE BOMBA DE RECIRCULACIÓN SILENCIOSA", "url": "https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-bombas-de-recirculacion-individuales-93", "keywords": ["bomba recirculadora 3 velocidades"]},
    "34": {"nombre": "SISTEMAS COMPLETOS DE BOMBA DE RECIRCULACIÓN Y CONTROL TÉRMICO", "url": "https://www.aisa.com.gt/shop/category/bomba-de-recirculacion-sistemas-bomba-de-recirculacion-94", "keywords": ["kit recirculación solar"]},
    "35": {"nombre": "BOMBAS PRESURIZADORAS DE AGUA PARA MEJORAR LA PRESIÓN DOMICILIARIA", "url": "https://www.aisa.com.gt/shop/category/bomba-presurizadora-35", "keywords": ["bomba presurizadora automática", "tanque hidroneumático"]},
    "36": {"nombre": "BOMBILLAS LED DE ALTA EFICIENCIA PARA HOGAR Y COMERCIO", "url": "https://www.aisa.com.gt/shop/category/bombilla-36", "keywords": ["bombilla LED", "iluminación eficiente"]},
    "37": {"nombre": "CONGELADORES ELÉCTRICOS HORIZONTALES PARA ALMACENAMIENTO DE ALIMENTOS", "url": "https://www.aisa.com.gt/shop/category/congelador-38", "keywords": ["congelador arcón", "congelador horizontal"]},
    "38": {"nombre": "CONTROLADORES DE CARGA MPPT DE ALTA EFICIENCIA PARA PANELES", "url": "https://www.aisa.com.gt/shop/category/controlador-mppt-39", "keywords": ["controlador MPPT", "eficiencia 99%"]},
    "39": {"nombre": "CONTROLADORES DE CARGA PWM ECONÓMICOS PARA SISTEMAS PEQUEÑOS", "url": "https://www.aisa.com.gt/shop/category/controlador-pwm-40", "keywords": ["controlador PWM"]},
    "40": {"nombre": "REPUESTOS ORIGINALES PARA CALENTADORES SOLARES Y TERMOTANQUES", "url": "https://www.aisa.com.gt/shop/category/repuesto-de-calentador-41", "keywords": ["ánodo de magnesio", "tubos de vacío"]},
    "41": {"nombre": "INVERSORES ON‑GRID MONOFÁSICOS PARA SISTEMAS CONECTADOS A LA RED", "url": "https://www.aisa.com.gt/shop/category/inv-ongrid-42", "keywords": ["inversor on-grid"]},
    "42": {"nombre": "INVERSORES DE AUTO CON ENTRADA 12V Y SALIDA 110V MODIFICADA", "url": "https://www.aisa.com.gt/shop/category/inv-car-43", "keywords": ["inversor coche", "onda modificada"]},
    "43": {"nombre": "INVERSORES DE ONDA PURA PROFESIONAL PARA EQUIPOS SENSIBLES", "url": "https://www.aisa.com.gt/shop/category/inv-pro-44", "keywords": ["inversor senoidal puro"]},
    "44": {"nombre": "SISTEMAS ON‑GRID DE CONSUMO ALTO PARA VIVIENDAS GRANDES Y OFICINAS", "url": "https://www.aisa.com.gt/shop/category/consumo-alto-on-grid-46", "keywords": ["kit solar 5kW on-grid"]},
    "45": {"nombre": "MINI KITS SOLARES PARA ILUMINACIÓN BÁSICA Y CARGA DE DISPOSITIVOS", "url": "https://www.aisa.com.gt/shop/category/mini-kit-48", "keywords": ["mini kit solar"]},
    "46": {"nombre": "KITS SOLARES PARA NECESIDAD BÁSICA DE ILUMINACIÓN Y TV PEQUEÑA", "url": "https://www.aisa.com.gt/shop/category/necesidad-basica-49", "keywords": ["kit solar básico 100W"]},
    "47": {"nombre": "KIT SOLAR BÁSICO MÁS AMENIDADES PARA VIVIENDA DE FIN DE SEMANA", "url": "https://www.aisa.com.gt/shop/category/basicos-mas-amenidades-50", "keywords": ["kit solar 200W"]},
    "48": {"nombre": "HOGAR SOLAR COMPLETO CON ELECTRODOMÉSTICOS ESENCIALES OFF‑GRID", "url": "https://www.aisa.com.gt/shop/category/hogar-solar-51", "keywords": ["kit solar vivienda 1kW"]},
    "49": {"nombre": "REPUESTOS Y HERRAJES PARA ESTRUCTURAS DE PANELES SOLARES", "url": "https://www.aisa.com.gt/shop/category/repuestos-y-herrajes-52", "keywords": ["soporte panel solar", "perfil aluminio"]},
    "50": {"nombre": "BOMBAS DE CAUDAL NO SUMERGIBLES PARA TRASVASE DE AGUA SUPERFICIAL", "url": "https://www.aisa.com.gt/shop/category/bomba-caudal-no-sumergible-54", "keywords": ["bomba centrífuga", "motobomba"]},
    "51": {"nombre": "SISTEMAS COMPLETOS DE BOMBAS SUMERGIBLES SOLARES PARA POZO", "url": "https://www.aisa.com.gt/shop/category/sistemas-bombas-sumergibles-56", "keywords": ["kit bomba sumergible solar"]},
    "52": {"nombre": "SISTEMAS DE BOMBAS PERIFÉRICAS CON PANEL SOLAR PARA TANQUES ELEVADOS", "url": "https://www.aisa.com.gt/shop/category/sistemas-de-bombas-perifericas-57", "keywords": ["bombeo periférico solar"]},
    "53": {"nombre": "SISTEMA DE BOMBA SUMERGIBLE DE CAUDAL ALTO CON DESALOJO DE AGUAS", "url": "https://www.aisa.com.gt/shop/category/sistema-bomba-caudal-sumergible-alto-d-59", "keywords": ["bomba sumergible trituradora"]},
    "54": {"nombre": "SISTEMA DE BOMBAS DE CAUDAL NO SUMERGIBLE PARA RIEGO DE SUPERFICIE", "url": "https://www.aisa.com.gt/shop/category/sistema-bombas-de-caudal-no-sumergible-60", "keywords": ["kit riego solar superficial"]},
    "55": {"nombre": "FLIPONES O INTERRUPTORES TERMOMAGNÉTICOS PARA PROTECCIÓN ELÉCTRICA", "url": "https://www.aisa.com.gt/shop/category/flipones-61", "keywords": ["breaker", "interruptor termomagnético"]},
    "56": {"nombre": "CONECTORES MC4 PARA PANELES SOLARES Y CABLEADO FOTOVOLTAICO", "url": "https://www.aisa.com.gt/shop/category/conectores-mc4-62", "keywords": ["conector MC4"]},
    "57": {"nombre": "CONGELADORES SOLARES DE CORRIENTE DIRECTA PARA ZONAS SIN RED", "url": "https://www.aisa.com.gt/shop/category/congelador-solar-64", "keywords": ["congelador solar 12/24V"]},
    "58": {"nombre": "REFRIGERADORES ELÉCTRICOS DOMÉSTICOS Y COMERCIALES EFICIENTES", "url": "https://www.aisa.com.gt/shop/category/refrigerador-65", "keywords": ["refrigerador 110V"]},
    "59": {"nombre": "SISTEMA ON‑GRID DE CONSUMO COMERCIAL ALTO PARA NEGOCIOS Y TALLERES", "url": "https://www.aisa.com.gt/shop/category/consumo-comercial-alto-on-grid-89", "keywords": ["kit solar comercial 10kW"]},
    "60": {"nombre": "SISTEMA ON‑GRID INDUSTRIAL PARA GRANDES DEMANDAS DE FÁBRICA", "url": "https://www.aisa.com.gt/shop/category/consumo-comercial-industrial-on-grid-90", "keywords": ["sistema solar industrial 30kW"]},
    "61": {"nombre": "SISTEMA ON‑GRID DE CONSUMO COMERCIAL INTERMEDIO PARA LOCAL PEQUEÑO", "url": "https://www.aisa.com.gt/shop/category/consumo-comercial-intermedio-on-grid-88", "keywords": ["kit solar 3kW negocio"]},
    "62": {"nombre": "INVERSORES HÍBRIDOS SOLARES CON RESPALDO DE BATERÍAS Y RED", "url": "https://www.aisa.com.gt/shop/category/inversor-hibrido-67", "keywords": ["inversor híbrido 5kW"]},
    "63": {"nombre": "COMPRESORES HERMÉTICOS PARA REFRIGERACIÓN Y AIRE ACONDICIONADO", "url": "https://www.aisa.com.gt/shop/category/compresor-68", "keywords": ["compresor hermético"]},
    "64": {"nombre": "SISTEMA DE BOMBA SUMERGIBLE DE ALTO CAUDAL PARA POZO PROFUNDO", "url": "https://www.aisa.com.gt/shop/category/sistema-bomba-caudal-sumergible-alto-69", "keywords": ["bomba sumergible 3HP"]},
    "65": {"nombre": "TODOS LOS CALENTADORES SOLARES EN UN SOLO LUGAR", "url": "https://www.aisa.com.gt/shop/category/all-calentadores-70", "keywords": ["catálogo calentadores"]},
    "66": {"nombre": "TANQUES DE ALMACENAMIENTO DE AGUA PLUVIAL Y RESERVA DOMICILIARIA", "url": "https://www.aisa.com.gt/shop/category/tanques-71", "keywords": ["tanque rotoplas", "cisterna"]},
    "67": {"nombre": "SISTEMA DE RESPALDO ENERGÉTICO BÁSICO CON BATERÍAS PARA HOGAR", "url": "https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-cb-72", "keywords": ["respaldo básico"]},
    "68": {"nombre": "SISTEMA DE RESPALDO INTERMEDIO PARA VIVIENDA CON ELECTRODOMÉSTICOS", "url": "https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-ci-73", "keywords": ["backup intermedio"]},
    "69": {"nombre": "SISTEMA DE RESPALDO AVANZADO PARA CASA COMPLETA ANTE APAGONES", "url": "https://www.aisa.com.gt/shop/category/sistemas-de-respaldo-ca-74", "keywords": ["respaldo 5kW"]},
    "70": {"nombre": "MARCOS Y SOPORTES EXCLUSIVOS PARA CALENTADORES SOLARES DE TUBOS", "url": "https://www.aisa.com.gt/shop/category/marcos-de-calentadores-75", "keywords": ["marco calentador solar"]},
    "71": {"nombre": "INVERSORES ON‑GRID TRIFÁSICOS PARA SISTEMAS COMERCIALES E INDUSTRIALES", "url": "https://www.aisa.com.gt/shop/category/inv-ongrid-trifasico-77", "keywords": ["inversor trifásico"]},
    "72": {"nombre": "CONTROLADORES ELECTRÓNICOS PARA BOMBAS SUMERGIBLES Y DE SUPERFICIE", "url": "https://www.aisa.com.gt/shop/category/controladores-bombas-82", "keywords": ["controlador nivel", "variador frecuencia"]},
    "73": {"nombre": "FLOTADORES ELÉCTRICOS Y MECÁNICOS PARA CONTROL DE NIVEL DE AGUA", "url": "https://www.aisa.com.gt/shop/category/flotadores-84", "keywords": ["flotador interruptor"]},
    "74": {"nombre": "MÁQUINAS DE HIELO ELÉCTRICAS COMERCIALES PARA CUBITOS Y ESCAMAS", "url": "https://www.aisa.com.gt/shop/category/ice-maker-85", "keywords": ["máquina hielo"]},
    "75": {"nombre": "MÁQUINAS DE GRANIZADOS Y RASPAOS COMERCIALES PARA NEGOCIO", "url": "https://www.aisa.com.gt/shop/category/ice-maker-maquinas-de-granizados-115", "keywords": ["raspadora hielo"]},
    "76": {"nombre": "SISTEMA ON‑GRID COMERCIAL BÁSICO PARA PEQUEÑOS EMPRENDIMIENTOS", "url": "https://www.aisa.com.gt/shop/category/consumo-comercial-basico-on-grid-91", "keywords": ["kit solar negocio pequeño"]},
    "77": {"nombre": "BOMBAS SUMERGIBLES PARA AGUAS RESIDUALES Y DESECHOS SÓLIDOS", "url": "https://www.aisa.com.gt/shop/category/bombas-de-caudal-sumergible-desechos-92", "keywords": ["bomba fecal"]},
    "78": {"nombre": "BOMBAS SUMERGIBLES DE ALTO CAUDAL PARA ABASTECIMIENTO Y RIEGO", "url": "https://www.aisa.com.gt/shop/category/bombas-sumergibles-alto-caudal-95", "keywords": ["bomba 5HP"]},
    "79": {"nombre": "SISTEMAS SOLARES HÍBRIDOS CONECTADOS A RED Y RESPALDO DE BATERÍA", "url": "https://www.aisa.com.gt/shop/category/sistemas-hibridos-96", "keywords": ["kit híbrido 3kW"]},
    "80": {"nombre": "CABLES ELÉCTRICOS GENERALES PARA INSTALACIONES Y CONEXIONES", "url": "https://www.aisa.com.gt/shop/category/cables-99", "keywords": ["cable THHN", "cable encauchetado"]},
    "81": {"nombre": "CABLE SOLAR ESPECIALIZADO PARA PANELES FOTOVOLTAICOS", "url": "https://www.aisa.com.gt/shop/category/cables-cable-solar-37", "keywords": ["cable solar 6mm"]},
    "82": {"nombre": "CABLE PARA BATERÍAS DE ALTA FLEXIBILIDAD Y GRAN SECCIÓN", "url": "https://www.aisa.com.gt/shop/category/cables-cable-bateria-100", "keywords": ["cable batería 2/0"]},
    "83": {"nombre": "CABLE SUMERGIBLE PLANO PARA BOMBAS DE POZO PROFUNDO", "url": "https://www.aisa.com.gt/shop/category/cables-cable-sumergible-101", "keywords": ["cable sumergible 4 hilos"]},
    "84": {"nombre": "CABLES TSJ PARA USO RUDO Y EXTENSIONES ELÉCTRICAS FLEXIBLES", "url": "https://www.aisa.com.gt/shop/category/cables-tsj-102", "keywords": ["cable TSJ"]},
    "85": {"nombre": "KIT DE CABLES PREARMADOS PARA CONEXIÓN DE SISTEMAS SOLARES", "url": "https://www.aisa.com.gt/shop/category/cables-kit-cable-103", "keywords": ["kit cable MC4"]},
    "86": {"nombre": "HIELERAS PORTÁTILES TERMOELÉCTRICAS Y DE COMPRESOR 12V/110V", "url": "https://www.aisa.com.gt/shop/category/hielera-portatil-122", "keywords": ["hielera eléctrica"]}
}

def obtener_fragmento_ontologia(topologia: Optional[str]) -> str:
    """Inyecta solo los bloques de la ontología necesarios para el contexto actual."""
    if not topologia:
        return "\n\n".join([ONTOLOGIA_BLOQUES.get("11", ""), ONTOLOGIA_BLOQUES.get("6", ""), ONTOLOGIA_BLOQUES.get("1", ""), ONTOLOGIA_BLOQUES.get("29", "")])
    
    bloques_requeridos = []
    if "On-Grid" in topologia:
        bloques_requeridos = ["11", "41", "38", "3", "29"]
    elif "Off-Grid" in topologia:
        bloques_requeridos = ["11", "26", "38", "14", "3", "46"]
    elif "Bombeo" in topologia:
        bloques_requeridos = ["6", "11", "3", "51"]
    elif "Calentamiento" in topologia:
        bloques_requeridos = ["1", "3"]
    elif "Refrigeración" in topologia or "Hielo" in topologia:
        bloques_requeridos = ["9", "11", "14", "26"]
    else:
        bloques_requeridos = list(ONTOLOGIA_BLOQUES.keys())
        
    return "\n\n".join([str(ONTOLOGIA_BLOQUES.get(b, str(b))) for b in bloques_requeridos])

# =====================================================================
# 4. HERRAMIENTAS (ASÍNCRONAS PARA SERVERLESS)
# =====================================================================
@tool
@auditar_fase(nombre_fase="Herramienta Backend (Envío Correo/WA)", criticidad="ALTA")
def procesar_oportunidad_backend(nombre_apellidos: str, departamento_municipio: str, consumo_actual: str, empresa_electrica: str, definicion_necesidad: str, listado_equipos_html: str, numero_whatsapp: str, resumen_18_palabras: str) -> str:
    """
    Ejecuta esta herramienta SOLO cuando el cliente acepte el pre-cálculo y el listado de equipos con links.
    Se encarga de enviar el WhatsApp y el Email al Controller a través de Gmail API y AcruxLab sin bloquear la UI.
    """
    def tarea_background():
        num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
        controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
        
        try:
            msg = MIMEMultipart()
            msg['To'] = controller_email
            msg['From'] = os.getenv("SMTP_USER", "AISA Bot")
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
El cliente ha validado los links. Pendiente de cotizar materiales de instalación, mano de obra, fletes y viáticos por el Controller."""
            msg.attach(MIMEText(cuerpo_correo, 'plain'))
            
            # Usar la nueva función de Gmail API
            enviar_correo_gmail_api(msg)
            
        except Exception as e:
            print(f"Error asíncrono en Gmail API: {str(e)}") 
            
        payload_wa = {
            "instance_id": APICHAT_INSTANCE,
            "number": num_limpio,
            "text": f"🚨 Lead Aprobado: {nombre_apellidos}\nAsunto: {resumen_18_palabras}\nUbicación: {departamento_municipio}\nEquipos:\n{listado_equipos_html}"
        }
        headers_wa = {"Authorization": f"Bearer {APICHAT_TOKEN}", "Content-Type": "application/json"}
        
        try:
            requests.post(APICHAT_ENDPOINT, json=payload_wa, headers=headers_wa, timeout=15)
        except Exception as e:
            print(f"Error asíncrono en WhatsApp: {str(e)}")

    # Despachamos el hilo y retornamos inmediatamente al LLM
    threading.Thread(target=tarea_background).start()
    return "¡Excelente! He enviado tu solicitud vía email y WhatsApp al equipo de ingeniería de AISA. El proceso de asignación se está ejecutando."

# =====================================================================
# 5. MANEJADOR GLOBAL DE ERRORES EN TIEMPO DE EJECUCIÓN (ASÍNCRONO)
# =====================================================================
def notificar_error_runtime(error_obj, traceback_str, session_data, prompt_fallido):
    def tarea_error_background():
        controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
        msg = MIMEMultipart()
        msg['To'] = controller_email
        msg['From'] = os.getenv("SMTP_USER", "AISA Bot")
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
            enviar_correo_gmail_api(msg)
            print("Notificación de error enviada asíncronamente.")
        except Exception as e_api:
            print(f"FALLO CRÍTICO: No se pudo enviar el correo de error. Razón: {e_api}")
            
    threading.Thread(target=tarea_error_background).start()

# =====================================================================
# 6. MOTOR COGNITIVO (SINGLETON PATTERN)
# =====================================================================
@st.cache_resource
def inicializar_motor_jarvi():
    """Compila el grafo y su memoria solo una vez por ciclo de contenedor."""
    memory = MemorySaver()
    graph_builder = StateGraph(AgentState)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([procesar_oportunidad_backend])

    def extraer_intencion_humana(messages: list) -> str:
        """
        Garantiza epistemológicamente que solo evaluamos la intención del usuario.
        Resuelve la ontología multimodal y previene excepciones de NoneType.
        """
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                if not msg.content:
                    return ""
                if isinstance(msg.content, str):
                    return msg.content.lower()
                if isinstance(msg.content, list):
                    # Manejo seguro para inputs multimodales (Visión Artificial)
                    textos = [str(bloque.get("text", "")).lower() for bloque in msg.content if isinstance(bloque, dict) and "text" in bloque]
                    return " ".join(textos)
        return ""

    # NODO 1: CLASIFICADOR EPISTEMOLÓGICO
    @auditar_fase(nombre_fase="Clasificador Epistemológico", criticidad="MEDIA")
    def clasificador_topologia_node(state: AgentState):
        messages = state.get("messages", [])
        ctx = state.get("contexto_tecnico", {
            "ciudad": None, "empresa_electrica": None, 
            "tarifa_base_gtq": None, "topologia": None, 
            "calculo_carga_completado": False, "requiere_auditoria_electrica": False
        })
        
        ultimo_mensaje = extraer_intencion_humana(messages)
        if not ultimo_mensaje: return {"contexto_tecnico": ctx}
      
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
    @auditar_fase(nombre_fase="Validador Geolocalización", criticidad="MEDIA")
    def validador_geolocalizacion_node(state: AgentState):
        ctx = state.get("contexto_tecnico", {
            "ciudad": None, "empresa_electrica": None, 
            "tarifa_base_gtq": None, "topologia": None, 
            "calculo_carga_completado": False, "requiere_auditoria_electrica": False
        })
        messages = state.get("messages", [])
        
        ultimo_mensaje = extraer_intencion_humana(messages)
        
        if not ultimo_mensaje: return {"contexto_tecnico": ctx}
       
        if not ctx.get("ciudad"):
            if any(k in ultimo_mensaje for k in ["guatemala", "mixco", "capital", "ciudad", "villa nueva", "petapa"]):
                ctx["ciudad"] = "Guatemala Metropolitana"
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
    @auditar_fase(nombre_fase="Motor Cognitivo (Chatbot LangGraph)", criticidad="ALTA")
    def chatbot_node(state: AgentState):
        ctx = state.get("contexto_tecnico", {
            "ciudad": None, "empresa_electrica": None, 
            "tarifa_base_gtq": None, "topologia": None, 
            "calculo_carga_completado": False, "requiere_auditoria_electrica": False
        })
        
        if ctx.get("requiere_auditoria_electrica"):
            regla_datos = "1. DEBES recopilar sutilmente: Nombre y Apellido, Departamento y Municipio, Consumo actual (kWh o gasto mensual), Empresa eléctrica, y Definición exacta de su necesidad."
        else:
            regla_datos = "1. DEBES recopilar sutilmente: Nombre y Apellido, Departamento y Municipio, y Definición exacta de su necesidad.\nOMITIR POR COMPLETO Y NO PREGUNTAR sobre consumo actual en kWh ni empresa eléctrica, ya que es irrelevante para este tipo de producto.\n(Si llamas a la herramienta final, envía 'N/A' en estos campos)."

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
        - HERRAMIENTA FINAL: Utiliza la herramienta `procesar_oportunidad_backend` para notificar al Controller humano. El parámetro `resumen_18_palabras` DEBE SER EXACTAMENTE DE 18 PALABRAS resumiendo la solución técnica que necesita el cliente.
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

    return graph_builder.compile(checkpointer=memory)

jarvi_graph = inicializar_motor_jarvi()

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
if "factura_procesada" not in st.session_state:
    st.session_state.factura_procesada = False

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
# LÓGICA DE CAPTURA DUAL Y MULTIMODAL (FOTO, AUDIO Y TEXTO)
# =====================================================================
st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional - Sólo para cálculo de Paneles)**")
col_img, col_cam = st.columns(2)

with col_img:
    factura_img = st.file_uploader("Sube una foto de tu factura", type=["jpg", "jpeg", "png"], key="file_factura")
with col_cam:
    factura_cam = st.camera_input("O toma una foto a la factura", key="cam_factura")

img_a_procesar = factura_img if factura_img else factura_cam

if img_a_procesar and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando tu factura con visión artificial..."):
        try:
            datos_factura = procesar_imagen_factura(img_a_procesar.getvalue())
            st.session_state.factura_procesada = True
            
            # Armamos el prompt automático con los datos extraídos
            empresa = datos_factura.get("empresa_electrica", "Desconocida")
            consumo = datos_factura.get("consumo_kwh", "Desconocido")
            monto = datos_factura.get("monto_factura", "Desconocido")
            
            prompt_factura = f"He subido mi factura eléctrica. Los datos detectados por el sistema de visión son: Empresa: {empresa}, Consumo: {consumo} kWh, Monto a pagar: Q{monto}. Por favor, tómalo en cuenta para mi requerimiento."
            st.session_state.pending_prompt = prompt_factura
            st.success("✅ Factura analizada correctamente. Los datos se han añadido a tu sesión.")
            st.rerun()
        except Exception as e:
            st.error(f"Error analizando la factura: {e}")

st.markdown("---")

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
                error_msg = str(e).lower()
                tb_str = traceback.format_exc()
                
                # Resiliencia ante fallos de memoria del checkpointer (Errores mostrados en Railway)
                if "checkpoint" in error_msg or "thread" in error_msg:
                    st.warning("🔄 Optimizando la memoria de la sesión técnica. Por favor, repite tu último mensaje.")
                    st.session_state.thread_id = str(uuid.uuid4())
                    st.rerun()
                else:
                    # Lógica original de reporte de fallos no relacionados a memoria
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
