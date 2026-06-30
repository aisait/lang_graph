import streamlit as st
import requests
import os
import uuid
import base64
import io
from openai import OpenAI

# --- Configuración de Entorno (Railway) ---
# BACKEND_URL apuntará a la URL pública de tu API FastAPI en Railway
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Usada aquí solo para Whisper y TTS

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# --- 1. Variables de Estado ---
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
    greeting = """¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar. Estamos para ayudarte a encontrar la mejor solución energética. ¿Sobre qué producto necesitas información hoy?

1. Calentadores Solares
2. Paneles Solares (Fuera de la red / lugares sin energía)
3. Paneles Solares (Ahorro en factura eléctrica)
4. Bombas de Agua Solares
5. Bombas de Calor para piscinas
6. Máquinas de hacer hielo (Ice Maker)
7. Hieleras
8. Otro

Cuéntame qué te interesa y, para darte una atención personalizada, ¿podrías indicarme también tu nombre y en qué zona te encuentras?"""
    st.session_state.messages = [{"role": "assistant", "content": greeting}]

# --- 2. Título e Instrucciones UI ---
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""
    ¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**. Para obtener la mejor asesoría, realizaremos estos pasos:
    * **1. Descubrimiento:** Identificamos tus necesidades reales, ubicación y consumo.
    * **2. Análisis Técnico:** Calculamos tus requerimientos base.
    * **3. Especificación:** Seleccionamos equipos con **enlaces directos** para tu validación.
    * **4. Presupuesto:** Generamos la lista base en GTQ (sin costos de instalación).
    * **5. Contacto directo:** Tras definir tu solución, enviaré la solicitud formal a nuestro Controller y te contactaremos por WhatsApp.
    """)

# Renderizado del historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 3. Lógica Multimodal (Captura de Factura) ---
st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional - Sólo para cálculo de Paneles)**")
col_img, col_cam = st.columns(2)

with col_img:
    factura_img = st.file_uploader("Sube una foto de tu factura", type=["jpg", "jpeg", "png"], key="file_factura")
with col_cam:
    factura_cam = st.camera_input("O toma una foto a la factura", key="cam_factura")

img_a_procesar = factura_img if factura_img else factura_cam

headers_api = {"Authorization": f"Bearer {API_KEY_SECRET}"}

if img_a_procesar and not st.session_state.factura_procesada:
    with st.spinner("🔍 Analizando tu factura con visión artificial en el servidor..."):
        try:
            base64_img = base64.b64encode(img_a_procesar.getvalue()).decode('utf-8')
            # Llama al nuevo endpoint aislado del backend
            res = requests.post(
                f"{BACKEND_URL}/vision/analyze", 
                json={"thread_id": st.session_state.thread_id, "image_base64": base64_img},
                headers=headers_api
            )
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                
                empresa = datos.get("empresa_electrica", "Desconocida")
                consumo = datos.get("consumo_kwh", "Desconocido")
                monto = datos.get("monto_factura", "Desconocido")
                
                # Armado del prompt silencioso
                prompt_factura = f"He subido mi factura eléctrica. Los datos detectados por el sistema de visión son: Empresa: {empresa}, Consumo: {consumo} kWh, Monto a pagar: Q{monto}. Por favor, tómalo en cuenta para mi requerimiento."
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada correctamente. Los datos se han añadido a tu sesión técnica.")
                st.rerun()
            else:
                st.error("Fallo al procesar la factura en el servidor.")
        except Exception as e:
            st.error(f"Error analizando la factura: {e}")

st.markdown("---")

# --- 4. Entrada de Usuario (Voz y Texto) ---
audio_value = st.audio_input(
    "🎤 Grabar mensaje de voz", 
    key=f"audio_input_{st.session_state.audio_key_counter}"
)
text_value = st.chat_input("¿Qué solución necesitas hoy: paneles, bombeo o respaldo?")

prompt = None

if text_value:
    st.session_state.is_voice_mode = False
    prompt = text_value

elif audio_value is not None:
    st.session_state.is_voice_mode = True
    with st.spinner("Escuchando tu mensaje de voz..."):
        try:
            audio_value.name = "audio.wav"
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_value
            )
            st.session_state.pending_prompt = transcript.text
            st.session_state.audio_key_counter += 1
            st.rerun()
        except Exception as e:
            st.error(f"Error al transcribir el audio: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None 

# --- 5. Comunicación Principal HTTP Cliente -> Backend ---
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Consultando en tiempo real con nuestro equipo de ingeniería especializada..."):
            try:
                payload = {
                    "thread_id": st.session_state.thread_id,
                    "message": prompt
                }
                
                # Reemplazo de n8n por tu FastAPI protegido
                response = requests.post(f"{BACKEND_URL}/chat", json=payload, headers=headers_api, timeout=60)
                
                if response.status_code == 200:
                    respuesta_ia = response.json().get("response", "Respuesta recibida.")
                    st.markdown(respuesta_ia)
                    st.session_state.messages.append({"role": "assistant", "content": respuesta_ia})
                    
                    # Síntesis TTS habilitada si el usuario envió audio
                    if st.session_state.is_voice_mode:
                        with st.spinner("Generando respuesta de voz..."):
                            try:
                                speech_response = client.audio.speech.create(
                                    model="tts-1",
                                    voice="alloy",
                                    input=respuesta_ia
                                )
                                audio_buffer = io.BytesIO()
                                for chunk in speech_response.iter_bytes(chunk_size=4096):
                                    audio_buffer.write(chunk)
                                audio_buffer.seek(0)
                                st.audio(audio_buffer, format="audio/mp3", autoplay=True)
                            except Exception as e:
                                st.error(f"Fallo en síntesis de voz: {e}")
                else:
                    st.error(f"Error en el servidor backend (Código: {response.status_code})")
            except Exception as e:
                st.error(f"Error de red al intentar conectar con la API: {str(e)}")
