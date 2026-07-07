"""
streamlit_app.py
Interfaz de usuario ligera de JARVI 2.0.03 (canal humano web).
Versión con logs de auditoría en la UI para depuración.
"""

import streamlit as st
import requests
import os
import uuid
import base64
import json

# ---------------------------------------------------------------------------
# 0. Configuración del entorno con logs de auditoría
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://jarvi-backend-production.up.railway.app"  # URL correcta del backend
).rstrip('/')

API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY")

# ---- Auditoría en UI ----
st.sidebar.markdown("### 🔍 Auditoría de conexión")
st.sidebar.code(f"BACKEND_URL = {BACKEND_URL}")
st.sidebar.code(f"API_KEY = {'✓ definida' if API_KEY_SECRET else '✗ NO DEFINIDA'}")

if not API_KEY_SECRET:
    st.error("❌ FALLO CRÍTICO: CHATBOT_MASTER_API_KEY no está definida. La aplicación no puede continuar.")
    st.stop()

# ---------------------------------------------------------------------------
# 1. Configuración de interfaz
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# ---------------------------------------------------------------------------
# 2. Estado de sesión
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
# Headers unificados
# ---------------------------------------------------------------------------
headers_api = {
    "Authorization": f"Bearer {API_KEY_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# ---------------------------------------------------------------------------
# 4. Captura multimodal: factura eléctrica
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
# 6. Comunicación con el backend (SSE, errores visibles, sin duplicados)
#    Ahora con logs de auditoría en la UI para depuración
# ---------------------------------------------------------------------------
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""

        # ---- Log de auditoría ----
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 📡 Última petición")
        st.sidebar.code(f"thread_id: {st.session_state.thread_id}")
        st.sidebar.code(f"prompt: {prompt[:50]}...")

        try:
            payload = {"thread_id": st.session_state.thread_id, "message": prompt}

            # ---- Intento de conexión ----
            st.sidebar.info(f"Conectando a {BACKEND_URL}/chat ...")
            response = requests.post(
                f"{BACKEND_URL}/chat",
                json=payload,
                headers=headers_api,
                stream=True,
                timeout=120
            )

            if response.status_code != 200:
                st.sidebar.error(f"Error HTTP {response.status_code}")
                st.error(f"Error backend {response.status_code}: {response.text[:200]}")
                st.stop()

            st.sidebar.success("Conexión establecida ✅")

            if response.encoding is None:
                response.encoding = "utf-8"

            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue

                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                if not isinstance(data, dict):
                    continue

                if data.get("type") == "token":
                    respuesta_completa += data["data"]
                    placeholder.markdown(respuesta_completa + "▌")

                elif data.get("type") == "final":
                    respuesta_final = data.get("response") or respuesta_completa
                    placeholder.markdown(respuesta_final)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": respuesta_final}
                    )
                    break

                elif data.get("type") == "error":
                    st.sidebar.error(f"Error en evento: {data.get('message')}")
                    st.error(data.get("message", "Error desconocido en el backend"))
                    break

            else:
                # si no hubo evento final, guardamos lo acumulado
                if respuesta_completa:
                    st.session_state.messages.append(
                        {"role": "assistant", "content": respuesta_completa}
                    )

            # TTS si modo voz activo
            if st.session_state.is_voice_mode and respuesta_completa:
                with st.spinner("Generando síntesis de voz..."):
                    tts_response = requests.post(
                        f"{BACKEND_URL}/tts",
                        json={"text": respuesta_completa, "voice": "alloy"},
                        headers=headers_api,
                        timeout=30
                    )
                    if tts_response.status_code == 200:
                        st.audio(tts_response.content, format="audio/mp3", autoplay=True)
                    else:
                        st.warning("Voz no disponible")

        except requests.exceptions.ConnectionError as e:
            st.sidebar.error(f"Error de conexión: {e}")
            st.error("❌ Error de conexión con la API. Verifica que el backend esté corriendo y que BACKEND_URL sea correcta.")
            st.sidebar.code(f"BACKEND_URL actual: {BACKEND_URL}")
        except Exception as e:
            st.sidebar.error(f"Excepción: {type(e).__name__}: {e}")
            st.error(f"Error inesperado: {str(e)}")
