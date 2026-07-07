"""
streamlit_app.py
Interfaz de usuario ligera de JARVI 2.0.03 con persistencia de thread_id y procesamiento SSE.
"""

import streamlit as st
import requests
import os
import uuid
import base64
import json
import time

# ---------------------------------------------------------------------------
# 0. Configuración del entorno
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "https://jarvi-backend-production.up.railway.app").rstrip('/')
API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY")

if not API_KEY_SECRET:
    st.error("❌ CHATBOT_MASTER_API_KEY no definida.")
    st.stop()

# ---------------------------------------------------------------------------
# 1. Configuración de la página y estado de sesión
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# --- Persistencia del thread_id en localStorage mediante JavaScript ---
st.markdown("""
<script>
    // Función para obtener thread_id del localStorage o generar uno nuevo
    function getThreadId() {
        let tid = localStorage.getItem('jarvi_thread_id');
        if (!tid) {
            tid = crypto.randomUUID();
            localStorage.setItem('jarvi_thread_id', tid);
        }
        return tid;
    }
    // Enviar el thread_id a Streamlit mediante un componente personalizado
    const threadId = getThreadId();
    const parent = window.parent;
    parent.postMessage({ type: 'streamlit:setComponentValue', value: threadId }, '*');
</script>
""", unsafe_allow_html=True)

# Inicializar thread_id desde la sesión (si no existe, se genera)
if "thread_id" not in st.session_state:
    # Intentar recuperar del localStorage (se hará mediante un input hidden)
    st.session_state.thread_id = str(uuid.uuid4())  # fallback

# Si el usuario recarga, se mantiene el mismo thread_id (si ya estaba en sesión)
# Para asegurar, usamos un componente personalizado (no implementado aquí por simplicidad).
# En su lugar, usamos st.query_params para persistencia temporal.
query_params = st.query_params
if "thread_id" in query_params:
    st.session_state.thread_id = query_params["thread_id"]
else:
    # Si no hay thread_id en query_params, usamos el de la sesión y lo guardamos en URL
    st.query_params["thread_id"] = st.session_state.thread_id

# Resto de variables de sesión
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
# 2. Interfaz de usuario
# ---------------------------------------------------------------------------
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**.
        Para obtener la mejor asesoría, realizaremos estos pasos:
        * **1. Descubrimiento:** Identificamos tus necesidades.
        * **2. Análisis Técnico:** Calculamos requerimientos.
        * **3. Especificación:** Seleccionamos equipos.
        * **4. Presupuesto:** Generamos la lista base.
        * **5. Contacto directo:** Gestión vía WhatsApp.""")

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

headers_api = {
    "Authorization": f"Bearer {API_KEY_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# ---------------------------------------------------------------------------
# 3. Factura (opcional)
# ---------------------------------------------------------------------------
st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional)**")
col_img, col_cam = st.columns(2)
with col_img:
    factura_img = st.file_uploader("Sube una foto", type=["jpg","jpeg","png"], key="file_factura")
with col_cam:
    factura_cam = st.camera_input("Toma una foto", key="cam_factura")
img_a_procesar = factura_img if factura_img else factura_cam
if img_a_procesar and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando..."):
        try:
            base64_img = base64.b64encode(img_a_procesar.getvalue()).decode('utf-8')
            res = requests.post(f"{BACKEND_URL}/vision/analyze",
                json={"thread_id": st.session_state.thread_id, "image_base64": base64_img},
                headers=headers_api, timeout=60)
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                prompt_factura = f"He subido mi factura. Datos: Empresa: {datos.get('empresa_electrica','N/A')}, Consumo: {datos.get('consumo_kwh','N/A')} kWh, Monto: Q{datos.get('monto_factura','N/A')}."
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada.")
                st.rerun()
            else:
                st.error(f"Error {res.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")
st.markdown("---")

# ---------------------------------------------------------------------------
# 4. Entrada de usuario
# ---------------------------------------------------------------------------
audio_value = st.audio_input("🎤 Grabar mensaje", key=f"audio_{st.session_state.audio_key_counter}")
text_value = st.chat_input("¿Qué solución necesitas hoy?")

prompt = None
if text_value:
    prompt = text_value
elif audio_value is not None:
    with st.spinner("Transcribiendo..."):
        try:
            files = {"audio": ("audio.wav", audio_value.read(), "audio/wav")}
            stt_response = requests.post(f"{BACKEND_URL}/stt", files=files,
                headers={"Authorization": f"Bearer {API_KEY_SECRET}"}, timeout=30)
            if stt_response.status_code == 200:
                transcript = stt_response.json().get("transcript", "")
                if transcript:
                    st.session_state.pending_prompt = transcript
                    st.session_state.audio_key_counter += 1
                    st.rerun()
                else:
                    st.error("No se pudo transcribir.")
            else:
                st.error(f"Error STT: {stt_response.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

# ---------------------------------------------------------------------------
# 5. Comunicación con el backend (SSE)
# ---------------------------------------------------------------------------
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""

        # --- Logs de auditoría ---
        st.sidebar.markdown("### 📡 Auditoría")
        st.sidebar.code(f"Thread ID: {st.session_state.thread_id}")
        st.sidebar.code(f"Prompt: {prompt[:80]}...")

        try:
            payload = {"thread_id": st.session_state.thread_id, "message": prompt}
            st.sidebar.info(f"Conectando a {BACKEND_URL}/chat ...")

            response = requests.post(
                f"{BACKEND_URL}/chat",
                json=payload,
                headers=headers_api,
                stream=True,
                timeout=120
            )

            if response.status_code != 200:
                st.sidebar.error(f"HTTP {response.status_code}")
                st.error(f"Error {response.status_code}: {response.text[:200]}")
                st.stop()

            st.sidebar.success("✅ Conectado")

            # Buffer para construir líneas completas
            buffer = ""
            for chunk in response.iter_content(chunk_size=128, decode_unicode=True):
                if chunk:
                    buffer += chunk
                    # Procesar líneas completas separadas por \n
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        json_str = line[6:]  # quitar 'data: '
                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(data, dict):
                            continue

                        # Procesar token
                        if "token" in data:
                            token = data["token"]
                            respuesta_completa += token
                            placeholder.markdown(respuesta_completa + "▌")
                        elif "contexto_tecnico" in data:
                            # Fin del stream
                            placeholder.markdown(respuesta_completa)
                            # Guardar en historial
                            st.session_state.messages.append(
                                {"role": "assistant", "content": respuesta_completa}
                            )
                            # Opcional: mostrar contexto en sidebar
                            st.sidebar.json(data["contexto_tecnico"])
                            break

            # Si no se recibió contexto, pero se acumuló algo
            if respuesta_completa and not any(m["role"]=="assistant" and m["content"]==respuesta_completa for m in st.session_state.messages):
                st.session_state.messages.append(
                    {"role": "assistant", "content": respuesta_completa}
                )

            # TTS si voz
            if st.session_state.is_voice_mode and respuesta_completa:
                tts_response = requests.post(f"{BACKEND_URL}/tts",
                    json={"text": respuesta_completa, "voice": "alloy"},
                    headers=headers_api, timeout=30)
                if tts_response.status_code == 200:
                    st.audio(tts_response.content, format="audio/mp3", autoplay=True)

        except requests.exceptions.ConnectionError:
            st.sidebar.error("🔌 Error de conexión")
            st.error("No se pudo conectar con el backend.")
        except Exception as e:
            st.sidebar.error(f"⚠️ {type(e).__name__}: {e}")
            st.error(f"Error inesperado: {e}")
