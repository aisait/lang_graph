"""
audio.py - Procesamiento de audio: Speech-to-Text y Text-to-Speech.
Usa OpenAI Whisper y TTS.
VERSIÓN 2.1 – Soporte para transformación de URLs de n8n (formato referencia a descarga directa).
"""
import os
import io
import re
import logging
import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

def _obtener_cliente_openai() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY_1") or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_2")
    if not api_key:
        raise RuntimeError("No se encontró ninguna API Key de OpenAI.")
    return OpenAI(api_key=api_key)

def descargar_audio_desde_url(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content

def transcribir_audio(audio_bytes: bytes, filename: str = "audio.mp3") -> str:
    client = _obtener_cliente_openai()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return transcript.text

# =============================================================================
# NUEVA FUNCIÓN: Transformar URL de referencia de n8n a URL de descarga directa
# =============================================================================
def construir_url_descarga_audio(url_referencia: str) -> str:
    """
    Transforma una URL de referencia de n8n (formato /web/chatresource/{id}/{uuid})
    en una URL de descarga directa del archivo .ogg.

    Ejemplo:
        Input:  https://deferral-dorsal-doorbell.ngrok-free.dev/web/chatresource/305109/0c932700-b94c-4fff-8770-89d6bfd871e8
        Output: https://deferral-dorsal-doorbell.ngrok-free.dev/web/content/305109/audio.ogg?access_token=0c932700-b94c-4fff-8770-89d6bfd871e8&download=1

    Parámetros:
        url_referencia (str): URL enviada por n8n.

    Retorna:
        str: URL de descarga directa.

    Lanza:
        ValueError: si la URL no tiene el formato esperado.
    """
    # Extraer dominio base (protocolo + dominio)
    dominio_match = re.match(r'(https?://[^/]+)', url_referencia)
    if not dominio_match:
        raise ValueError("URL inválida: no se pudo extraer el dominio.")

    dominio = dominio_match.group(1)

    # Extraer ID del recurso y UUID
    # Patrón esperado: /web/chatresource/{id}/{uuid}
    patron = r'/web/chatresource/(\d+)/([a-f0-9\-]+)'
    match = re.search(patron, url_referencia)
    if not match:
        raise ValueError("URL inválida: no coincide con el patrón de n8n (/web/chatresource/{id}/{uuid}).")

    id_recurso = match.group(1)
    uuid = match.group(2)

    # Construir URL de descarga
    url_descarga = f"{dominio}/web/content/{id_recurso}/audio.ogg?access_token={uuid}&download=1"
    return url_descarga

# =============================================================================
# FUNCIÓN PRINCIPAL DE TRANSCRIPCIÓN DESDE URL (MODIFICADA)
# =============================================================================
def transcribir_audio_desde_url(url: str) -> str:
    """
    Descarga y transcribe audio desde una URL.
    Si la URL es del tipo de referencia de n8n (/web/chatresource/...), se transforma
    automáticamente a la URL de descarga directa antes de la descarga.
    """
    # Si la URL parece ser de referencia (contiene '/web/chatresource/'), transformar
    if '/web/chatresource/' in url:
        logger.info(f"Detectada URL de referencia de n8n. Transformando...")
        try:
            url = construir_url_descarga_audio(url)
            logger.info(f"URL transformada a: {url}")
        except ValueError as e:
            logger.error(f"Error al transformar URL de audio: {e}")
            # Si falla, se intenta descargar la URL original (por si acaso)
            # Pero es probable que falle, así que se lanza la excepción.
            raise

    # Descargar y transcribir
    audio_bytes = descargar_audio_desde_url(url)
    filename = url.split('/')[-1].split('?')[0] or "audio.ogg"
    return transcribir_audio(audio_bytes, filename)

def sintetizar_voz(texto: str, voice: str = "alloy") -> bytes:
    client = _obtener_cliente_openai()
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=texto
    )
    return response.content
