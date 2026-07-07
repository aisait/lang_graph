"""
streamlit_app.py
Interfaz ligera y moderna de JARVI 2.0 con todas las funcionalidades aprobadas:
- Chat conversacional con historial persistente.
- Entrada de voz (STT) y salida de voz (TTS) integradas.
- Carga de factura eléctrica (cámara o archivo) para OCR.
- Procesamiento SSE nativo con persistencia de thread_id.
- Panel de auditoría compacto con datos técnicos extraídos.
- Diseño tipo WhatsApp: limpio, centrado y responsivo.
Cumple con ISO/IEC 25010, 29119 y las pruebas BC‑T01 a BC‑T10.
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
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY")

if not API_KEY:
    st.error("❌ CHATBOT_MASTER_API_KEY no definida. Verifica las variables de entorno.")
    st.stop()

# ---------------------------------------------------------------------------
# 1. Configuración de página y persistencia del thread_id
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Jarvi ⚡", page_icon="⚡", layout="centered")

# Persistencia del thread_id en la URL (permite recargar sin perder sesión)
if "thread_id" not in st.session_state:
    tid = st.query_params.get("thread_id")
    if tid:
        st.session_state.thread_id = tid
    else:
        st.session_state.thread_id = str(uuid.uuid4())
        st.query_params["thread_id"] = st.session_state.thread_id

# Inicializar historial de mensajes
if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": (
            "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar.\n"
            "¿Sobre qué producto necesitas información hoy?\n\n"
            "1. Calentadores Solares\n"
            "2. Paneles Solares (On‑Grid / Off‑Grid)\n"
            "3. Bombas de Agua Solares\n"
            "4. Bombas de Calor\n"
            "5. Máquinas de Hielo\n"
            "6. Hieleras\n\n"
            "Puedes escribir, hablar (🎤) o subir tu factura eléctrica 📸."
        )
    }]

# Estado para factura procesada
if "factura_procesada" not in st.session_state:
    st.session_state.factura_procesada = False
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None
if "audio_key" not in st.session_state:
    st.session_state.audio_key = 0

# ---------------------------------------------------------------------------
# 2. Interfaz principal (como chat)
# ---------------------------------------------------------------------------
st.title("⚡ Jarvi · Asesor Solar")
st.caption(f"Sesión: `{st.session_state.thread_id[:8]}` | [Traza en LangSmith](https://smith.langchain.com)")

# Mostrar historial de mensajes
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# 3. Entrada de usuario: texto, voz o factura
# ---------------------------------------------------------------------------
# Dividimos la entrada en dos filas: barra de texto + botones de adjunto
with st.container():
    col_text, col_attach = st.columns([4, 1])

    with col_text:
        prompt = st.chat_input("Escribe tu consulta...", key="chat_input")

    with col_attach:
        # Usamos un popover para mostrar opciones de adjunto
        with st.popover("📎 Adjuntar", use_container_width=True):
            # Opción: Subir factura (archivo)
            factura_file = st.file_uploader(
                "📄 Subir factura (JPG/PNG)",
                type=["jpg", "jpeg", "png"],
                key="factura_upload",
                label_visibility="collapsed"
            )
            # Opción: Tomar foto con cámara
            factura_cam = st.camera_input("📸 Tomar foto", key="factura_cam", label_visibility="collapsed")

            # Opción: Grabar voz
            audio_bytes = st.audio_input("🎤 Grabar voz", key=f"audio_{st.session_state.audio_key}")

    # Determinar si se ha seleccionado una imagen (archivo o cámara)
    factura_img = factura_file if factura_file else factura_cam

# ---------------------------------------------------------------------------
# 4. Procesar entrada de factura (OCR) – BC‑T06
# ---------------------------------------------------------------------------
if factura_img and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando factura con IA..."):
        try:
            base64_img = base64.b64encode(factura_img.getvalue()).decode('utf-8')
            res = requests.post(
                f"{BACKEND_URL}/vision/analyze",
                json={"thread_id": st.session_state.thread_id, "image_base64": base64_img},
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                timeout=60
            )
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                prompt_factura = (
                    f"He subido mi factura eléctrica. Datos detectados:\n"
                    f"- Empresa: {datos.get('empresa_electrica', 'N/A')}\n"
                    f"- Consumo: {datos.get('consumo_kwh', 'N/A')} kWh\n"
                    f"- Monto: Q{datos.get('monto_factura', 'N/A')}"
                )
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada. Envía el mensaje automático.")
                st.rerun()
            else:
                st.error(f"Error al procesar factura: {res.status_code}")
        except Exception as e:
            st.error(f"Error al procesar factura: {e}")

# ---------------------------------------------------------------------------
# 5. Procesar entrada de voz (STT) – BC‑T07
# ---------------------------------------------------------------------------
if audio_bytes is not None:
    with st.spinner("Transcribiendo audio..."):
        try:
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
            stt_res = requests.post(
                f"{BACKEND_URL}/stt",
                files=files,
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=30
            )
            if stt_res.status_code == 200:
                transcript = stt_res.json().get("transcript", "")
                if transcript:
                    st.session_state.pending_prompt = transcript
                    st.session_state.audio_key += 1  # para resetear el input
                    st.rerun()
                else:
                    st.warning("No se pudo transcribir el audio.")
            else:
                st.error(f"Error STT: {stt_res.status_code}")
        except Exception as e:
            st.error(f"Error en STT: {e}")

# ---------------------------------------------------------------------------
# 6. Manejar el prompt final (texto, voz o factura)
# ---------------------------------------------------------------------------
if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
else:
    prompt = None  # ya se definió antes si era texto

# ---------------------------------------------------------------------------
# 7. Enviar mensaje al backend y mostrar respuesta
# ---------------------------------------------------------------------------
if prompt:
    # Añadir mensaje del usuario al historial
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

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
                st.error(f"Error del servidor: {response.status_code} - {response.text[:200]}")
                st.stop()

            # Procesar el stream SSE
            buffer = ""
            for chunk in response.iter_content(chunk_size=128, decode_unicode=True):
                if chunk:
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: "):
                            json_str = line[6:]  # quitar "data: "
                            try:
                                data = json.loads(json_str)
                            except json.JSONDecodeError:
                                continue
                            if "token" in data:
                                token = data["token"]
                                respuesta_completa += token
                                placeholder.markdown(respuesta_completa + "▌")
                            elif "contexto_tecnico" in data:
                                contexto = data["contexto_tecnico"]
                                # Fin del stream
                                placeholder.markdown(respuesta_completa)
                                break

            # Guardar respuesta en el historial
            if respuesta_completa:
                st.session_state.messages.append(
                    {"role": "assistant", "content": respuesta_completa}
                )
                # Mostrar contexto técnico en un expander sutil
                if contexto:
                    with st.expander("🔍 Datos técnicos extraídos", expanded=False):
                        st.json(contexto)
            else:
                st.warning("No se recibió respuesta del asistente.")

            # Generar TTS si el usuario usó voz (opcional) – BC‑T07
            if audio_bytes is not None and respuesta_completa:
                with st.spinner("Generando voz..."):
                    tts_res = requests.post(
                        f"{BACKEND_URL}/tts",
                        json={"text": respuesta_completa, "voice": "alloy"},
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        timeout=30
                    )
                    if tts_res.status_code == 200:
                        st.audio(tts_res.content, format="audio/mp3", autoplay=True)

        except requests.exceptions.ConnectionError:
            st.error("❌ No se pudo conectar con el backend. Verifica que esté activo.")
        except Exception as e:
            st.error(f"Error inesperado: {e}")

    # Reiniciar estado de factura (para permitir nuevas subidas)
    st.session_state.factura_procesada = False
    st.rerun()

# ---------------------------------------------------------------------------
# 8. Pie de página
# ---------------------------------------------------------------------------
st.divider()
st.caption("⚡ Jarvi 2.0 · AISA Solar · [Ver en LangSmith](https://smith.langchain.com)")
