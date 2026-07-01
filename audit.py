"""
audit.py
Módulo de auditoría y gestión de errores de JARVI 2.0.
Proporciona decoradores para capturar metadatos de ejecución y un sistema de
notificación por correo ante errores graves.
Estándares aplicados: ISO/IEC/IEEE 12207 (Ciclo de vida), ISO/IEC 26514 (Documentación),
ISO/IEC 25010 (Calidad), ISO/IEC 29119 (Pruebas de caja negra).
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

# ---------------------------------------------------------------------------
# Configuración del logger central de auditoría
# Prueba de caja negra: al iniciar el servicio, los logs deben aparecer en la
# consola de Railway con el formato definido.
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("JarviAudit")


def enviar_correo_gmail_api(msg_multipart: MIMEMultipart) -> None:
    """
    Envía un correo electrónico utilizando la API de Gmail con OAuth2.
    Esta función mantiene la implementación original del monolito.

    Parámetros:
        msg_multipart (MIMEMultipart): mensaje completo a enviar.

    Prueba de caja negra (ISO/IEC 29119):
        - Simular un error que llame a esta función y verificar que el destinatario
          recibe el correo con el asunto y cuerpo esperados.
        - Si las credenciales Gmail son incorrectas, el logger debe registrar
          "Falló el envío de correo de auditoría" y no interrumpir el flujo.
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
    Decorador para funciones del grafo. Captura excepciones, registra metadatos
    y relanza el error para el manejo centralizado.

    Uso:
        @auditar_fase(nombre_fase="Clasificador Topológico", criticidad="MEDIA")
        def mi_nodo(state):
            ...

    Prueba de caja negra:
        - Ejecutar una función decorada que no falle: no debe aparecer ningún
          registro de error.
        - Ejecutar una función que lance ValueError: el logger debe mostrar un
          JSON con los campos 'fase', 'error_tipo', 'error_mensaje', etc., y
          el traceback completo. La excepción debe propagarse hacia arriba.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # timestamp de inicio para auditoría (no se usa actualmente pero se
            # puede almacenar en futuros análisis)
            _ = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                resultado = func(*args, **kwargs)
                return resultado
            except Exception as e:
                timestamp_error = datetime.datetime.now(datetime.timezone.utc).isoformat()
                tb_str = traceback.format_exc()

                # Metadatos estructurados de la excepción
                error_payload = {
                    "fase": nombre_fase,
                    "criticidad": criticidad,
                    "timestamp_utc": timestamp_error,
                    "funcion_origen": func.__name__,
                    "error_tipo": type(e).__name__,
                    "error_mensaje": str(e),
                    "argumentos_posicionales": str(args)[:500],
                    "argumentos_llave": str(kwargs)[:500]
                }

                # Registro en el logger para observabilidad en Railway
                logger.error(f"🚨 [METADATOS AUDITORÍA ISO]: {json.dumps(error_payload, indent=2)}")
                logger.error(f"📋 [TRACEBACK ORIGINAL]:\n{tb_str}")

                # Relanzamos la excepción para no alterar el flujo del grafo/API
                raise e
        return wrapper
    return decorator


def notificar_error_runtime(error_obj: Exception, traceback_str: str,
                            session_data: dict, prompt_fallido: str) -> None:
    """
    Envía una notificación por correo electrónico al controlador cuando ocurre
    un error grave en tiempo de ejecución. Se ejecuta en un hilo independiente
    para no bloquear la respuesta al usuario.

    Parámetros:
        error_obj: la excepción capturada.
        traceback_str: traceback completo en formato texto.
        session_data: diccionario con el estado actual del grafo/sesión.
        prompt_fallido: último mensaje del usuario que provocó el error.

    Prueba de caja negra (ISO/IEC 29119):
        - Forzar un error y llamar a esta función. El Controller debe recibir
          un correo con el asunto 'ERROR CRÍTICO JARVI PRODUCTION' y en el cuerpo
          deben aparecer el tipo de error, el prompt y el snapshot de la sesión.
        - Si el envío falla, el logger debe registrar el fallo sin afectar el
          hilo principal.
    """
    def tarea_error_background():
        """Ejecuta el envío del correo en segundo plano."""
        controller_email = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
        msg = MIMEMultipart()
        msg['To'] = controller_email
        msg['From'] = os.getenv("SMTP_USER", "Jarvi Telemetry <notificaciones@aisa.com.gt>")
        msg['Subject'] = f"🚨 ERROR CRÍTICO JARVI PRODUCTION - FASE: {session_data.get('fase_actual', 'RUNTIME')}"

        # Serializamos el estado de la sesión para adjuntarlo al correo
        try:
            session_json = json.dumps(session_data, indent=2, default=str)
        except Exception:
            session_json = str(session_data)

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

    # Lanzamos el envío en un hilo separado para evitar bloqueos
    threading.Thread(target=tarea_error_background).start()
