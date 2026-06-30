import os
import json
import traceback
import datetime
import threading
import base64
import functools
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Infraestructura de Autenticación de Google API de tu entorno de producción
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Configuración estándar de logs para visualizar directo en la consola de Railway
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("JarviAudit")

def enviar_correo_gmail_api(msg_multipart):
    """
    Conserva fielmente tu lógica del monolito para envío de correos 
    utilizando la API de Gmail mediante el flujo de Refresh Token.
    """
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
        logger.info("⚡ [AUDITORÍA API] Notificación de error enviada exitosamente a Ingeniería.")
    except Exception as e:
        logger.error(f"❌ [AUDITORÍA CRÍTICA] Falló el envío de correo de auditoría: {str(e)}")

def auditar_fase(nombre_fase: str, criticidad: str = "ALTA"):
    """
    Decorador de tu monolito original. 
    Mantiene el estándar ISO/Técnico de captura de contexto, variables y excepciones.
    Reemplaza st.write/st.error por logging de backend preservando los diccionarios.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            timestamp_inicio = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                # Ejecución normal del nodo del grafo
                resultado = func(*args, **kwargs)
                return resultado
            except Exception as e:
                timestamp_error = datetime.datetime.now(datetime.timezone.utc).isoformat()
                tb_str = traceback.format_exc()
                
                # Consolidación técnica de metadatos (Lógica de Negocio Original)
                error_payload = {
                    "fase": nombre_fase,
                    "criticidad": criticidad,
                    "timestamp_utc": timestamp_error,
                    "funcion_origen": func.__name__,
                    "error_tipo": type(e).__name__,
                    "error_mensaje": str(e),
                    "argumentos_posicionales": str(args)[:500], # Evita truncados masivos en logs
                    "argumentos_llave": str(kwargs)[:500]
                }
                
                # Print altamente técnico en la consola de Railway (Facilita debug en tiempo real)
                logger.error(f"🚨 [METADATOS AUDITORÍA ISO]: {json.dumps(error_payload, indent=2)}")
                logger.error(f"📋 [TRACEBACK ORIGINAL]:\n{tb_str}")
                
                # Re-lanzamos la excepción para que el middleware del api_server o LangGraph la manejen
                raise e
        return wrapper
    return decorator

def notificar_error_runtime(error_obj, traceback_str, session_data, prompt_fallido):
    """
    Conserva la lógica exacta del monolito para empaquetar el snapshot de la sesión,
    el estado del contexto técnico de Jarvi, el prompt que falló y enviarlo 
    en un hilo asíncrono para no congelar la API.
    """
    def tarea_error_background():
        controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
        msg = MIMEMultipart()
        msg['To'] = controller_email
        msg['From'] = os.getenv("SMTP_USER", "Jarvi Telemetry <notificaciones@aisa.com.gt>")
        msg['Subject'] = f"🚨 ERROR CRÍTICO JARVI PRODUCTION - FASE: {session_data.get('fase_actual', 'RUNTIME')}"
        
        try:
            session_json = json.dumps(session_data, indent=2, default=str)
        except Exception:
            session_json = str(session_data)

        # Cuerpo del correo con la estructura exacta que exige tu auditoría
        cuerpo_correo = f"""=====================================================================
REPORTE DE ERROR DE RUNTIME - JARVI (MODELO DESACOPLADO AISA)
=====================================================================
TIMESTAMP UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}
TIPO DE EXCEPCIÓN: {type(error_obj).__name__}
MENSAJE DEL ERROR: {str(error_obj)}

ÚLTIMO PROMPT ENVIADO POR EL USUARIO:
"{prompt_fallido}"

---------------------------------------------------------------------
SNAPSHOT DE LA SESIÓN TÉCNICA (ESTADO DEL GRAFO):
---------------------------------------------------------------------
{session_json}

---------------------------------------------------------------------
TRACEBACK COMPLETO DE INGENIERÍA:
---------------------------------------------------------------------
{traceback_str}
====================================================================="""
        
        msg.attach(MIMEText(cuerpo_correo, 'plain'))
        enviar_correo_gmail_api(msg)
            
    # Ejecución asíncrona idéntica a tu desarrollo original
    threading.Thread(target=tarea_error_background).start()
