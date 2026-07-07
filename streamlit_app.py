"""
streamlit_app.py
Interfaz tipo WhatsApp para JARVI 2.0.
Barra de entrada con herramientas integradas (cámara, archivo, voz).
Procesamiento SSE, persistencia de thread_id, auditoría compacta.
Cumple ISO/IEC 25010, 29119 y BC‑T01 a BC‑T10.
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
# CSS personalizado para estilo WhatsApp
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Fondo suave y tipografía */
    .stApp {
        background-color: #ece5dd;
        font-family: 'Segoe UI', sans-serif;
    }
    /* Burbujas de mensaje */
    .stChatMessage {
        padding: 0.5rem 1rem;
        border-radius: 20px;
        max-width: 80%;
        margin-bottom: 0.3rem;
    }
    .stChatMessage[data-testid="user"] {
        background-color: #dcf8c6;
        align-self: flex-end;
        margin-left: auto;
    }
    .stChatMessage[data-testid="assistant"] {
        background-color: white;
        align-self: flex-start;
        margin-right: auto;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    /* Barra de entrada fija */
    .stChatInput {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: white;
        padding: 10px 20px;
        border-top: 1px solid #ddd;
        z-index: 100;
    }
    /* Ocultar elementos innecesarios */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    /* Ajustes de márgenes */
    .main > div {
        padding-bottom: 80px;
    }
    /* Íconos de herramientas en la barra */
    .tool-icon {
        font-size: 1.8rem;
        cursor: pointer;
        margin: 0 8px;
        color: #555;
    }
    .tool-icon:hover {
        color: #25D366;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Estado de sesión y persistencia del thread_id
# ---------------------------------------------------------------------------
if "thread_id" not in st.session_state:
    tid = st.query_params.get("thread_id")
    if tid:
        st.session_state.thread_id = tid
    else:
        st.session_state.thread_id = str(uuid.uuid4())
        st.query_params["thread_id"] = st.session_state.thread_id

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": "👋 ¡Hola! Soy Jarvi, tu asesor técnico de AISA Solar.\n\n¿Sobre qué producto necesitas información?\n\n1️⃣ Calentadores Solares\n2️⃣ Paneles Solares (On‑Grid / Off‑Grid)\n3️⃣ Bombas de Agua Solares\n4️⃣ Bombas de Calor\n5️⃣ Máquinas de Hielo\n6️⃣ Hieleras\n\nPuedes escribir, grabar voz 🎤 o subir tu factura eléctrica 📸."
    }]

if "factura_procesada" not in st.session_state:
    st.session_state.factura_procesada = False
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None
if "audio_key" not in st.session_state:
    st.session_state.audio_key = 0

# ---------------------------------------------------------------------------
# Cabecera compacta
# ---------------------------------------------------------------------------
st.markdown("<h2 style='text-align: center; color: #075e54;'>⚡ Jarvi · Asesor Solar</h2>", unsafe_allow_html=True)
st.caption(f"Sesión: `{st.session_state.thread_id[:8]}`")

# ---------------------------------------------------------------------------
# Mostrar historial de mensajes (burbujas)
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Entrada de usuario con herramientas integradas
# ---------------------------------------------------------------------------
# Usamos un contenedor fijo para la barra de entrada
with st.container():
    col_input, col_tools = st.columns([5, 1], gap="small")
    with col_input:
        prompt = st.chat_input("Escribe tu mensaje...", key="chat_input")
    with col_tools:
        # Popover de herramientas (clip)
        with st.popover("📎", use_container_width=False):
            st.caption("Adjuntar")
            factura_file = st.file_uploader(
                "📄 Factura (JPG/PNG)",
                type=["jpg", "jpeg", "png"],
                key="factura_upload",
                label_visibility="collapsed"
            )
            factura_cam = st.camera_input("📸 Tomar foto", key="factura_cam", label_visibility="collapsed")
        # Botón de grabar voz (abre el input de audio)
        audio_bytes = st.audio_input("🎤", key=f"audio_{st.session_state.audio_key}", label_visibility="collapsed")

# ---------------------------------------------------------------------------
# Procesar factura (OCR)
# ---------------------------------------------------------------------------
factura_img = factura_file if factura_file else factura_cam
if factura_img and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando factura..."):
        try:
            base64_img = base64.b64encode(factura_img.getvalue()).decode('utf-8')
            res = requests.post(
                f"{BACKEND_URL}/vision/analyze",
                json={"thread_id": st.session_state.thread_id, "image_base64": base64_img},
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=60
            )
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                prompt_factura = (
                    f"📄 Factura detectada:\n"
                    f"- Empresa: {datos.get('empresa_electrica', 'N/A')}\n"
                    f"- Consumo: {datos.get('consumo_kwh', 'N/A')} kWh\n"
                    f"- Monto: Q{datos.get('monto_factura', 'N/A')}"
                )
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada.")
                st.rerun()
            else:
                st.error(f"Error OCR: {res.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")

# ---------------------------------------------------------------------------
# Procesar entrada de voz (STT)
# ---------------------------------------------------------------------------
if audio_bytes is not None:
    with st.spinner("🔄 Transcribiendo..."):
        try:
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
            res = requests.post(
                f"{BACKEND_URL}/stt",
                files=files,
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=30
            )
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

# ---------------------------------------------------------------------------
# Manejar el prompt final (texto, factura o voz)
# ---------------------------------------------------------------------------
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
else:
    prompt = prompt  # del chat_input

# ---------------------------------------------------------------------------
# Enviar mensaje al backend y mostrar respuesta
# ---------------------------------------------------------------------------
if prompt:
    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Preparar respuesta del asistente
    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""
        contexto = {}

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {"thread_id": st.session_state.thread_id, "message": prompt}

        try:
            response = requests.post(
                f"{BACKEND_URL}/chat",
                json=payload,
                headers=headers,
                stream=True,
                timeout=120
            )

            if response.status_code != 200:
                st.error(f"Error {response.status_code}: {response.text[:200]}")
                st.stop()

            # Procesar SSE
            buffer = ""
            for chunk in response.iter_content(chunk_size=128, decode_unicode=True):
                if chunk:
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: "):
                            json_str = line[6:]
                            try:
                                data = json.loads(json_str)
                            except:
                                continue
                            if "token" in data:
                                token = data["token"]
                                respuesta_completa += token
                                placeholder.markdown(respuesta_completa + "▌")
                            elif "contexto_tecnico" in data:
                                contexto = data["contexto_tecnico"]
                                placeholder.markdown(respuesta_completa)
                                break

            if respuesta_completa:
                st.session_state.messages.append(
                    {"role": "assistant", "content": respuesta_completa}
                )
                # Auditoría compacta
                if contexto:
                    with st.expander("🔍 Datos técnicos", expanded=False):
                        st.json(contexto)

                # TTS si el usuario usó voz
                if audio_bytes is not None:
                    with st.spinner("🔊 Generando voz..."):
                        tts_res = requests.post(
                            f"{BACKEND_URL}/tts",
                            json={"text": respuesta_completa, "voice": "alloy"},
                            headers={"Authorization": f"Bearer {API_KEY}"},
                            timeout=30
                        )
                        if tts_res.status_code == 200:
                            st.audio(tts_res.content, format="audio/mp3", autoplay=True)
            else:
                st.warning("No se recibió respuesta.")

        except requests.exceptions.ConnectionError:
            st.error("❌ No se pudo conectar con el backend.")
        except Exception as e:
            st.error(f"Error: {e}")

    # Reiniciar estado de factura
    st.session_state.factura_procesada = False
    st.rerun()

# ---------------------------------------------------------------------------
# Pie de página
# ---------------------------------------------------------------------------
st.caption("⚡ Jarvi 2.0 · AISA Solar")
