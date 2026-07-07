"""
streamlit_app.py - Interfaz JARVI con depuración SSE visible.
Muestra los eventos recibidos y la respuesta final.
"""

import streamlit as st
import requests
import os
import uuid
import base64
import json
import time

# ---------------------------------------------------------------------------
# Configuración y seguridad
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "https://jarvi-backend-production.up.railway.app").rstrip('/')
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY")

if not API_KEY:
    st.error("❌ CHATBOT_MASTER_API_KEY no definida.")
    st.stop()

# ---------------------------------------------------------------------------
# Estado de sesión y thread_id persistente
# ---------------------------------------------------------------------------
if "thread_id" not in st.session_state:
    tid = st.query_params.get("thread_id")
    st.session_state.thread_id = tid if tid else str(uuid.uuid4())
    st.query_params["thread_id"] = st.session_state.thread_id

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": "👋 ¡Hola! Soy Jarvi, tu asesor técnico de AISA Solar.\n\n¿Sobre qué producto necesitas información?\n1️⃣ Calentadores Solares\n2️⃣ Paneles Solares (On‑Grid / Off‑Grid)\n3️⃣ Bombas de Agua Solares\n4️⃣ Bombas de Calor\n5️⃣ Máquinas de Hielo\n6️⃣ Hieleras\n\nPuedes escribir, grabar voz 🎤 o subir tu factura eléctrica 📸."
    }]

if "factura_procesada" not in st.session_state:
    st.session_state.factura_procesada = False
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None
if "audio_key" not in st.session_state:
    st.session_state.audio_key = 0

# ---------------------------------------------------------------------------
# Estilo CSS simple
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .stApp { background-color: #ece5dd; }
    .stChatMessage { border-radius: 20px; padding: 8px 16px; max-width: 80%; }
    .stChatMessage[data-testid="user"] { background-color: #dcf8c6; margin-left: auto; }
    .stChatMessage[data-testid="assistant"] { background-color: white; margin-right: auto; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
    .main > div { padding-bottom: 80px; }
    footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h2 style='text-align: center; color: #075e54;'>⚡ Jarvi · Asesor Solar</h2>", unsafe_allow_html=True)
st.caption(f"Sesión: `{st.session_state.thread_id[:8]}`")

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Barra de entrada
# ---------------------------------------------------------------------------
with st.container():
    col_input, col_attach = st.columns([5, 1])
    with col_input:
        prompt = st.chat_input("Escribe tu mensaje...")
    with col_attach:
        with st.popover("📎"):
            factura_file = st.file_uploader("📄 Factura", type=["jpg","jpeg","png"], label_visibility="collapsed")
            factura_cam = st.camera_input("📸 Tomar foto", label_visibility="collapsed")
        audio_bytes = st.audio_input("🎤", key=f"audio_{st.session_state.audio_key}", label_visibility="collapsed")

# Procesar factura (OCR)
factura_img = factura_file if factura_file else factura_cam
if factura_img and not st.session_state.factura_procesada:
    with st.spinner("Analizando factura..."):
        try:
            b64 = base64.b64encode(factura_img.getvalue()).decode()
            res = requests.post(f"{BACKEND_URL}/vision/analyze",
                json={"thread_id": st.session_state.thread_id, "image_base64": b64},
                headers={"Authorization": f"Bearer {API_KEY}"}, timeout=60)
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                st.session_state.pending_prompt = (
                    f"📄 Factura: {datos.get('empresa_electrica','N/A')}, "
                    f"{datos.get('consumo_kwh','N/A')} kWh, Q{datos.get('monto_factura','N/A')}"
                )
                st.success("✅ Factura analizada.")
                st.rerun()
            else:
                st.error(f"Error: {res.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")

# Procesar voz (STT)
if audio_bytes is not None:
    with st.spinner("Transcribiendo..."):
        try:
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
            res = requests.post(f"{BACKEND_URL}/stt", files=files,
                headers={"Authorization": f"Bearer {API_KEY}"}, timeout=30)
            if res.status_code == 200:
                transcript = res.json().get("transcript", "")
                if transcript:
                    st.session_state.pending_prompt = transcript
                    st.session_state.audio_key += 1
                    st.rerun()
                else:
                    st.warning("No se pudo transcribir.")
            else:
                st.error(f"Error STT: {res.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")

# Obtener prompt final
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

# ---------------------------------------------------------------------------
# Enviar mensaje y mostrar respuesta con depuración visible
# ---------------------------------------------------------------------------
if prompt:
    # Añadir mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""
        contexto = {}
        eventos = []  # para depuración

        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        payload = {"thread_id": st.session_state.thread_id, "message": prompt}

        try:
            response = requests.post(f"{BACKEND_URL}/chat", json=payload, headers=headers, stream=True, timeout=120)
            if response.status_code != 200:
                st.error(f"Error {response.status_code}: {response.text[:200]}")
                st.stop()

            # Procesar SSE de forma simple: leer línea por línea
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                json_str = line[6:]
                try:
                    data = json.loads(json_str)
                except:
                    continue

                # Guardar para depuración
                eventos.append(data)

                if "token" in data:
                    respuesta_completa += data["token"]
                    placeholder.markdown(respuesta_completa + "▌")
                elif "contexto_tecnico" in data:
                    contexto = data["contexto_tecnico"]
                    # Una vez recibido el contexto, finaliza el stream
                    placeholder.markdown(respuesta_completa)
                    break

            # Mostrar eventos de depuración en un expander
            with st.expander("🔍 Depuración SSE (eventos recibidos)"):
                st.json(eventos)

            # Guardar respuesta en historial
            if respuesta_completa:
                st.session_state.messages.append({"role": "assistant", "content": respuesta_completa})
                if contexto:
                    with st.expander("📊 Datos técnicos extraídos"):
                        st.json(contexto)

                # TTS si hubo voz
                if audio_bytes is not None:
                    with st.spinner("Generando voz..."):
                        tts_res = requests.post(f"{BACKEND_URL}/tts",
                            json={"text": respuesta_completa, "voice": "alloy"},
                            headers={"Authorization": f"Bearer {API_KEY}"}, timeout=30)
                        if tts_res.status_code == 200:
                            st.audio(tts_res.content, format="audio/mp3", autoplay=True)
            else:
                st.warning("No se recibió respuesta del asistente.")

        except requests.exceptions.ConnectionError:
            st.error("❌ No se pudo conectar con el backend.")
        except Exception as e:
            st.error(f"Error: {e}")

    st.session_state.factura_procesada = False
    st.rerun()

st.caption("⚡ Jarvi 2.0 · AISA Solar")
