"""
streamlit_app.py
Interfaz de usuario ligera de JARVI 2.0 (canal humano web).
Actúa exclusivamente como cliente de la API central; no contiene
lógica de negocio, inteligencia artificial ni acceso directo a Odoo.
Todas las operaciones de voz, texto e imagen se delegan a la API.

Estándares aplicados:
- ISO/IEC/IEEE 12207:2008 (Ciclo de vida): este módulo es la interfaz
  de usuario final del sistema.
- ISO/IEC 26514:2021 (Documentación de software): se documentan todas las
  secciones y flujos de interacción.
- ISO/IEC 25010:2011 (Calidad del producto):
  * Usabilidad: mensajes de bienvenida, indicadores de progreso y
    manejo de errores amigables.
  * Rendimiento: streaming de tokens para baja latencia percibida.
  * Mantenibilidad: separación total de la lógica de negocio.
- ISO/IEC 29119:2022 (Pruebas de software - caja negra):
  Las pruebas sugeridas se incluyen en los comentarios de cada sección.
"""

import streamlit as st
import requests
import os
import uuid
import base64
import io
import json

# ---------------------------------------------------------------------------
# 0. Configuración del entorno (Railway - Producción)
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "https://jarvi-backend-production.up.railway.app:8000")
if BACKEND_URL.endswith('/'):
    BACKEND_URL = BACKEND_URL[:-1]

API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")

# ---------------------------------------------------------------------------
# 1. Configuración de la interfaz de usuario
# Prueba de caja negra: al cargar la página, debe verse el título
# "Jarvi ⚡ Agente de Soluciones de AISA Solar" y el favicon ⚡.
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# ---------------------------------------------------------------------------
# 2. Variables de estado de la sesión (persistencia completa)
# Prueba de caja negra: cada pestaña/ventana del navegador debe generar
# un thread_id único y mantener el historial de mensajes por separado.
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
# 3. Título e instrucciones de uso
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
# Renderizado del historial de la conversación
# Prueba de caja negra: los mensajes del usuario aparecen a la derecha
# y los del asistente a la izquierda, con formato Markdown.
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# 4. Captura multimodal: factura eléctrica (imagen)
# Prueba de caja negra:
#   - Subir una imagen de factura: debe aparecer "✅ Factura analizada
#     correctamente." y en el chat se inyecta un prompt con los datos.
#   - Subir una imagen no válida: la API debe responder con error y se
#     muestra un mensaje en rojo.
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
headers_api = {"Authorization": f"Bearer {API_KEY_SECRET}", "Content-Type": "application/json"}

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
                st.error(
                    f"Fallo al procesar la factura en el servidor "
                    f"(Código {res.status_code})."
                )
        except Exception as e:
            st.error(f"Error técnico analizando la factura: {e}")

st.markdown("---")

# ---------------------------------------------------------------------------
# 5. Entrada del usuario: voz y texto
# Prueba de caja negra:
#   - Escribir en el campo de texto y enviar: se debe agregar el mensaje
#     al historial y comenzar el streaming de respuesta.
#   - Grabar un mensaje de voz: debe aparecer "Transcribiendo..." y luego
#     el texto transcrito se inyecta como prompt automáticamente.
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
            # Enviar el audio a la API central (/stt) en lugar de usar OpenAI directamente
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
                    st.error("No se pudo transcribir el audio (texto vacío).")
            elif stt_response.status_code == 501:
                st.error("Funcionalidad de voz no disponible en la API todavía.")
            else:
                st.error(f"Error del servidor al transcribir: {stt_response.status_code}")
        except Exception as e:
            st.error(f"Error al enviar audio a la API: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

# ---------------------------------------------------------------------------
# 6. Comunicación con el backend: envío del mensaje y recepción del streaming
# Prueba de caja negra:
#   - Enviar un mensaje de texto: debe aparecer el mensaje del usuario y
#     la respuesta del asistente renderizarse token a token.
#   - Si el modo voz está activo, al finalizar la respuesta se debe
#     generar y reproducir un audio automáticamente.
#   - Si el backend no está disponible, debe mostrarse un error de conexión.
# ---------------------------------------------------------------------------
if prompt:
    # Añadir mensaje del usuario al historial
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
            # Stream SSE desde la API central
            with requests.post(
                f"{BACKEND_URL}/chat",
                json=payload,
                headers=headers_api,
                stream=True,
                timeout=60
            ) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith("data: "):
                                data_json = json.loads(decoded_line[6:])
                                # Acumulación de tokens en tiempo real
                                if "token" in data_json:
                                    respuesta_completa += data_json["token"]
                                    placeholder.markdown(respuesta_completa + "▌")
                                # Contexto técnico final
                                if "contexto_tecnico" in data_json:
                                    contexto_tecnico = data_json["contexto_tecnico"]
                                # Manejo de errores desde la API
                                if "error" in data_json:
                                    st.error(data_json["error"])
                    # Renderizado final sin el cursor
                    placeholder.markdown(respuesta_completa)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": respuesta_completa}
                    )

                    # Si el modo voz está activo, solicitar síntesis de voz a la API
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
                else:
                    st.error(
                        f"Error del servidor backend (Código: {response.status_code}). "
                        "Verifica los logs de la API."
                    )
        except requests.exceptions.ConnectionError:
            st.error("Error fatal de conexión con la API. Asegúrate de que el backend esté en ejecución.")
        except Exception as e:
            st.error(f"Error inesperado: {str(e)}")
