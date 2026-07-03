"""
streamlit_app.py
Interfaz de usuario ligera de JARVI 2.0.03 (canal humano web).
Cliente robusto con manejo correcto de streaming SSE,
timeouts, errores y delegación total a la API central.
"""

import streamlit as st
import requests
import os
import uuid
import base64
import io
import json
import time

# ---------------------------------------------------------------------------
# 0. Configuración del entorno
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://cliente-api-production-c7bb.up.railway.app"  # sin puerto explícito
).rstrip('/')

API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")

# ---------------------------------------------------------------------------
# 1. Configuración de la interfaz
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# ---------------------------------------------------------------------------
# 2. Variables de estado
# ---------------------------------------------------------------------------
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
    greeting = (
        "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar. "
        "Estamos para ayudarte a encontrar la mejor solución energética. "
        "¿Sobre qué producto necesitas información hoy?\n\n"
        "1. Calentadores Solares\n"
        "2. Paneles Solares (Fuera de la red)\n"
        "3. Paneles Solares (Ahorro en factura eléctrica)\n"
        "4. Bombas de Agua Solares\n"
        "5. Bombas de Calor para piscinas\n"
        "6. Máquinas de hacer hielo\n"
        "7. Hieleras\n\n"
        "Cuéntame qué te interesa y, para darte una atención personalizada, "
        "¿podrías indicarme tu nombre y en qué zona te encuentras?"
    )
    st.session_state.messages = [{"role": "assistant", "content": greeting}]

# ---------------------------------------------------------------------------
# 3. Título e instrucciones
# ---------------------------------------------------------------------------
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown(
        """¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**.
        Para obtener la mejor asesoría, realizaremos estos pasos:

        * **1. Descubrimiento:** Identificamos tus necesidades.
        * **2. Análisis Técnico:** Calculamos requerimientos.
        * **3. Especificación:** Seleccionamos equipos.
        * **4. Presupuesto:** Generamos la lista base.
        * **5. Contacto directo:** Gestión vía WhatsApp."""
    )

# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# 4. Captura de factura (igual que antes, delegando a API)
# ---------------------------------------------------------------------------
st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional)**")
col_img, col_cam = st.columns(2)

with col_img:
    factura_img = st.file_uploader(
        "Sube una foto de tu factura", type=["jpg", "jpeg", "png"],
        key="file_factura"
    )
with col_cam:
    factura_cam = st.camera_input("O toma una foto a la factura", key="cam_factura")

img_a_procesar = factura_img if factura_img else factura_cam
headers_api = {
    "Authorization": f"Bearer {API_KEY_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

if img_a_procesar and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando factura con visión artificial..."):
        try:
            base64_img = base64.b64encode(img_a_procesar.getvalue()).decode('utf-8')
            res = requests.post(
                f"{BACKEND_URL}/vision/analyze",
                json={"thread_id": st.session_state.thread_id, "image_base64": base64_img},
                headers=headers_api,
                timeout=60
            )
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                prompt_factura = (
                    f"He subido mi factura eléctrica. Datos detectados: "
                    f"Empresa: {datos.get('empresa_electrica', 'N/A')}, "
                    f"Consumo: {datos.get('consumo_kwh', 'N/A')} kWh, "
                    f"Monto: Q{datos.get('monto_factura', 'N/A')}."
                )
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada correctamente.")
                st.rerun()
            else:
                st.error(f"Fallo al procesar la factura (Código {res.status_code}).")
        except Exception as e:
            st.error(f"Error técnico analizando la factura: {e}")

st.markdown("---")

# ---------------------------------------------------------------------------
# 5. Entrada de usuario (voz y texto)
# ---------------------------------------------------------------------------
audio_value = st.audio_input(
    "🎤 Grabar mensaje de voz",
    key=f"audio_input_{st.session_state.audio_key_counter}"
)
text_value = st.chat_input("¿Qué solución necesitas hoy?")

prompt = None
if text_value:
    st.session_state.is_voice_mode = False
    prompt = text_value
elif audio_value is not None:
    st.session_state.is_voice_mode = True
    with st.spinner("Transcribiendo mensaje de voz..."):
        try:
            audio_bytes = audio_value.read()
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
            stt_response = requests.post(
                f"{BACKEND_URL}/stt",
                files=files,
                headers={"Authorization": f"Bearer {API_KEY_SECRET}"},
                timeout=30
            )
            if stt_response.status_code == 200:
                transcript = stt_response.json().get("transcript", "")
                if transcript:
                    st.session_state.pending_prompt = transcript
                    st.session_state.audio_key_counter += 1
                    st.rerun()
                else:
                    st.error("No se pudo transcribir el audio.")
            elif stt_response.status_code == 501:
                st.error("Funcionalidad de voz no disponible.")
            else:
                st.error(f"Error del servidor al transcribir: {stt_response.status_code}")
        except Exception as e:
            st.error(f"Error al enviar audio a la API: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

# ---------------------------------------------------------------------------
# 6. Comunicación con el backend (MEJORADO)
# ---------------------------------------------------------------------------
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""
        contexto_tecnico = {}

        try:
            payload = {
                "thread_id": st.session_state.thread_id,
                "message": prompt
            }

            # ------------------------------------------------
            # Petición con timeout amplio y manejo robusto
            # ------------------------------------------------
            response = requests.post(
                f"{BACKEND_URL}/chat",
                json=payload,
                headers=headers_api,
                stream=True,
                timeout=120
            )

            if response is None:
                st.error("Backend no disponible")
                st.stop()

            if response.status_code != 200:
                st.error(f"Error backend {response.status_code}: {response.text}")
                st.stop()

            content_type = response.headers.get("Content-Type", "")

            # ================== CASO 1: SSE STREAMING ==================
            if "text/event-stream" in content_type:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])

                            if "token" in data:
                                respuesta_completa += data["token"]
                                placeholder.markdown(respuesta_completa + "▌")

                            if "contexto_tecnico" in data:
                                contexto_tecnico = data["contexto_tecnico"]

                            if "error" in data:
                                st.error(data["error"])

                        except json.JSONDecodeError:
                            # a veces llega texto no JSON, lo agregamos como token
                            respuesta_completa += line[6:]
                            placeholder.markdown(respuesta_completa + "▌")

            # ================== CASO 2: JSON NORMAL ==================
            else:
                try:
                    data = response.json()
                    respuesta_completa = (
                        data.get("response")
                        or data.get("answer")
                        or data.get("message")
                        or str(data)
                    )
                except Exception:
                    respuesta_completa = response.text

            # ------------ Render final y TTS ------------
            placeholder.markdown(respuesta_completa)
            st.session_state.messages.append(
                {"role": "assistant", "content": respuesta_completa}
            )

            if st.session_state.is_voice_mode and respuesta_completa:
                with st.spinner("Generando síntesis de voz..."):
                    tts_response = requests.post(
                        f"{BACKEND_URL}/tts",
                        json={"text": respuesta_completa, "voice": "alloy"},
                        headers=headers_api,
                        timeout=30
                    )
                    if tts_response.status_code == 200:
                        audio_bytes = tts_response.content
                        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
                    elif tts_response.status_code == 501:
                        st.warning("Síntesis de voz no disponible en la API.")
                    else:
                        st.error(f"Error al generar voz: {tts_response.status_code}")

        except requests.exceptions.ConnectionError:
            st.error("Error fatal de conexión con la API. Asegúrate de que el backend esté en ejecución.")
        except Exception as e:
            st.error(f"Error inesperado: {str(e)}")
