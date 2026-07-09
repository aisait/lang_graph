"""
audio.py - Procesamiento de audio: Speech-to-Text y Text-to-Speech.
Usa OpenAI Whisper y TTS.
"""
import os
import io
import requests
from openai import OpenAI

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

def transcribir_audio_desde_url(url: str) -> str:
    audio_bytes = descargar_audio_desde_url(url)
    filename = url.split('/')[-1] or "audio.mp3"
    return transcribir_audio(audio_bytes, filename)

def sintetizar_voz(texto: str, voice: str = "alloy") -> bytes:
    client = _obtener_cliente_openai()
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=texto
    )
    return response.content
