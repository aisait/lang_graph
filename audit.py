"""
audit.py
═══════════════════════════════════════════════════════════════════════
Auditoría y gestión de errores con sanitización de PII.
Cumple con ISO/IEC 27001 A.8.2 (tratamiento de información) y DORA (registro de incidentes).

Pruebas de caja negra (ISO/IEC 29119):
    BC‑T11: Forzar error → verificar que los logs y correos no contengan PII.
"""
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
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from utils.sanitize import sanitize_pii, sanitize_dict

logger = logging.getLogger("JarviAudit")

def enviar_correo_gmail_api(msg_multipart: MIMEMultipart) -> None:
    """Envía correo de auditoría vía Gmail API (OAuth2)."""
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
        logger.info("⚡ [AUDITORÍA API] Notificación de error enviada a Ingeniería.")
    except Exception as e:
        logger.error(f"❌ [AUDITORÍA CRÍTICA] Falló el envío de correo de auditoría: {str(e)}")

def auditar_fase(nombre_fase: str, criticidad: str = "ALTA"):
    """Decorador que captura excepciones y registra metadata para auditoría."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                timestamp_error = datetime.datetime.now(datetime.timezone.utc).isoformat()
                tb_str = traceback.format_exc()
                # Sanitizar argumentos para evitar PII en logs (ISO/IEC 27001)
                args_sanitized = sanitize_dict(str(args)[:500])
                kwargs_sanitized = sanitize_dict(str(kwargs)[:500])
                error_payload = {
                    "fase": nombre_fase,
                    "criticidad": criticidad,
                    "timestamp_utc": timestamp_error,
                    "funcion_origen": func.__name__,
                    "error_tipo": type(e).__name__,
                    "error_mensaje": sanitize_pii(str(e)),
                    "argumentos_posicionales": args_sanitized,
                    "argumentos_llave": kwargs_sanitized
                }
                logger.error(f"🚨 [METADATOS AUDITORÍA ISO]: {json.dumps(error_payload, indent=2)}")
                logger.error(f"📋 [TRACEBACK ORIGINAL]:\n{tb_str}")
                raise e
        return wrapper
    return decorator

def notificar_error_runtime(error_obj: Exception, traceback_str: str,
                            session_data: dict, prompt_fallido: str) -> None:
    """
    Notifica error crítico por correo, sanitizando PII.
    """
    def tarea_error_background():
        # Sanitización (ISO/IEC 27001 A.8.2)
        session_sanitized = sanitize_dict(session_data)
        prompt_sanitized = sanitize_pii(prompt_fallido)
        controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
        msg = MIMEMultipart()
        msg['To'] = controller_email
        msg['From'] = os.getenv("SMTP_USER", "Jarvi Telemetry <notificaciones@aisa.com.gt>")
        msg['Subject'] = f"🚨 ERROR CRÍTICO JARVI PRODUCTION - FASE: {session_sanitized.get('fase_actual', 'RUNTIME')}"
        try:
            session_json = json.dumps(session_sanitized, indent=2, default=str)
        except Exception:
            session_json = str(session_sanitized)

        cuerpo_correo = f"""=====================================================================
REPORTE DE ERROR DE RUNTIME - JARVI (MODELO DESACOPLADO AISA)
=====================================================================
TIMESTAMP UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}
TIPO DE EXCEPCIÓN: {type(error_obj).__name__}
MENSAJE DEL ERROR: {sanitize_pii(str(error_obj))}

ÚLTIMO PROMPT ENVIADO POR EL USUARIO:
"{prompt_sanitized}"

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

    threading.Thread(target=tarea_error_background).start()
