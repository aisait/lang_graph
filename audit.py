# audit.py
import streamlit as st
import functools
import traceback
import datetime
import threading
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import config

def enviar_correo_error_base(msg_multipart):
    """Auxiliar aislado para envío seguro vía Gmail API."""
    creds = Credentials(
        token=None,
        refresh_token=config.os.getenv("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.os.getenv("GMAIL_CLIENT_ID"),
        client_secret=config.os.getenv("GMAIL_CLIENT_SECRET")
    )
    try:
        service = build('gmail', 'v1', credentials=creds)
        raw_msg = base64.urlsafe_b64encode(msg_multipart.as_bytes()).decode('utf-8')
        service.users().messages().send(userId="me", body={'raw': raw_msg}).execute()
    except Exception as e:
        print(f"Error crítico en logger de auditoría: {e}")

def auditar_fase(nombre_fase: str, criticidad: str = "ALTA"):
    """Decorador de auditoría para trazabilidad de datos algorítmicos (ISO 42001)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                st.error(f"❌ Error en {nombre_fase} (Criticidad: {criticidad})")
                tb_str = traceback.format_exc()
                timestamp_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                with st.expander("🛠️ Detalles Técnicos de Auditoría", expanded=True):
                    st.markdown("### Contexto de Fallo")
                    st.text(f"Timestamp: {timestamp_iso}\nFunción: {func.__name__}")
                    st.code(tb_str, language="python")
                raise e
        return wrapper
    return decorator

def notificar_error_runtime(error_obj, traceback_str, session_data, prompt_fallido):
    """Reporte de fallos asíncrono para cumplimiento de Niveles de Servicio ITIL."""
    def tarea_error_background():
        msg = MIMEMultipart()
        msg['To'] = config.CONTROLLER_EMAIL
        msg['From'] = config.SMTP_USER
        msg['Subject'] = f"🚨 ERROR JARVI PRODUCTION - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        cuerpo = f"""Fallo No Controlado Detectado por el Sistema de Auditoría:
TIPO: {type(error_obj).__name__}
MENSAJE: {str(error_obj)}
PROMPT EVALUADO: {prompt_fallido}
TRACEBACK METADATA:
{traceback_str}
ESTADO DE LA SESIÓN CONVERSACIONAL:
{session_data}"""
        msg.attach(MIMEText(cuerpo, 'plain'))
        enviar_correo_error_base(msg)

    threading.Thread(target=tarea_error_background).start()
