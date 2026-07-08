"""
audio.py - Procesamiento de audio: Speech-to-Text y Text-to-Speech.
Usa OpenAI Whisper y TTS.
"""
import os
from openai import OpenAI

def _obtener_cliente_openai() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY_1") or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_2")
    if not api_key:
        raise RuntimeError("No se encontró ninguna API Key de OpenAI.")
    return OpenAI(api_key=api_key)

def transcribir_audio(audio_bytes: bytes, filename: str = "audio.mp3") -> str:
    """
    Transcribe un archivo de audio usando Whisper.
    """
    client = _obtener_cliente_openai()
    # Guardar temporalmente en memoria o usar BytesIO
    import io
    from openai import OpenAI
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )
    return transcript.text

def sintetizar_voz(texto: str, voice: str = "alloy") -> bytes:
    """
    Genera audio a partir de texto usando TTS de OpenAI.
    """
    client = _obtener_cliente_openai()
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=texto
    )
    # response.content es bytes
    return response.content
