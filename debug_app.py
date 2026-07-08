"""
debug_app.py - Consola de depuración CLI para JARVI 2.0.
Proxy SSE y endpoints para procesamiento de imágenes y audio (archivo o URL).
"""
import os
import json
import uuid
import logging
from flask import Flask, render_template, request, Response, jsonify, stream_with_context
import requests
from urllib.parse import urljoin
import base64

import vision
import audio

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "https://jarvi-backend-production.up.railway.app").rstrip('/')
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY")
DEBUG_PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug-console")

if not API_KEY:
    logger.error("CHATBOT_MASTER_API_KEY no definida. Las peticiones fallarán.")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Ruta principal
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('debug.html', backend_url=BACKEND_URL)

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "cliente-debug", "backend": BACKEND_URL})

# ---------------------------------------------------------------------------
# Proxy SSE
# ---------------------------------------------------------------------------
@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "Mensaje requerido"}), 400

    thread_id = data.get('thread_id', str(uuid.uuid4()))
    message = data['message']
    logger.info(f"Debug request | thread: {thread_id} | msg: {message[:50]}...")

    def generate():
        yield f"data: {json.dumps({'info': f'[DEBUG] Conectando a {BACKEND_URL}'})}\n\n"
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        payload = {"thread_id": thread_id, "message": message}
        try:
            resp = requests.post(
                urljoin(BACKEND_URL, '/chat'),
                json=payload,
                headers=headers,
                stream=True,
                timeout=120
            )
            if resp.status_code != 200:
                yield f"data: {json.dumps({'error': f'HTTP {resp.status_code}: {resp.text[:200]}'})}\n\n"
                return
            for line in resp.iter_lines(decode_unicode=True):
                if line:
                    yield f"data: {line}\n\n"
        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'error': '[ERROR] No se pudo conectar al backend'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'[ERROR] {str(e)}'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )

# ---------------------------------------------------------------------------
# ENDPOINT: Análisis de imágenes (archivo o URL)
# ---------------------------------------------------------------------------
@app.route('/api/vision/analyze', methods=['POST'])
def analyze_image():
    """
    Acepta:
      - multipart/form-data con campo 'image'
      - JSON con campo 'url'
    """
    # Caso 1: URL en JSON
    if request.is_json:
        data = request.get_json()
        if 'url' in data:
            try:
                datos = vision.procesar_imagen_desde_url(data['url'])
                return jsonify({"extracted_data": datos})
            except Exception as e:
                logger.error(f"Error en vision desde URL: {e}")
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Se requiere campo 'url'"}), 400

    # Caso 2: Archivo subido
    if 'image' not in request.files:
        return jsonify({"error": "No se envió ninguna imagen"}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400
    img_bytes = file.read()
    base64_img = base64.b64encode(img_bytes).decode('utf-8')
    try:
        datos = vision.procesar_imagen_factura(base64_img)
        return jsonify({"extracted_data": datos})
    except Exception as e:
        logger.error(f"Error en vision: {e}")
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ENDPOINT: Speech-to-Text (archivo o URL)
# ---------------------------------------------------------------------------
@app.route('/api/stt', methods=['POST'])
def speech_to_text():
    # Caso 1: URL en JSON
    if request.is_json:
        data = request.get_json()
        if 'url' in data:
            try:
                transcript = audio.transcribir_audio_desde_url(data['url'])
                return jsonify({"transcript": transcript})
            except Exception as e:
                logger.error(f"Error en STT desde URL: {e}")
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Se requiere campo 'url'"}), 400

    # Caso 2: Archivo subido
    if 'audio' not in request.files:
        return jsonify({"error": "No se envió ningún archivo de audio"}), 400
    file = request.files['audio']
    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400
    audio_bytes = file.read()
    try:
        transcript = audio.transcribir_audio(audio_bytes, file.filename)
        return jsonify({"transcript": transcript})
    except Exception as e:
        logger.error(f"Error en STT: {e}")
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ENDPOINT: Text-to-Speech (siempre JSON)
# ---------------------------------------------------------------------------
@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "Se requiere campo 'text'"}), 400
    text = data['text']
    voice = data.get('voice', 'alloy')
    try:
        audio_bytes = audio.sintetizar_voz(text, voice)
        return Response(audio_bytes, mimetype='audio/mpeg', headers={
            'Content-Disposition': 'attachment; filename="speech.mp3"'
        })
    except Exception as e:
        logger.error(f"Error en TTS: {e}")
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Historial (mock)
# ---------------------------------------------------------------------------
@app.route('/api/history/<thread_id>', methods=['GET'])
def get_history(thread_id):
    return jsonify({"thread_id": thread_id, "messages": []})

# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=DEBUG_PORT, debug=False)
