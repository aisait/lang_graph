import streamlit as st
import requests
import os
import uuid
import base64
import io
import json
import time
from openai import OpenAI

# --- 0. Configuración de Entorno (Railway - Producción) ---
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
if BACKEND_URL.endswith('/'):
    BACKEND_URL = BACKEND_URL[:-1]

API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None
    st.error("Error crítico: OPENAI_API_KEY no configurada.")

# --- 1. Configuración de Interfaz ---
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# --- 2. Variables de Estado ---
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "is_voice_mode" not in st.session_state:
    st.session_state.is_voice_mode = False
if "audio_key_counter" not in st.session_state:
    st.session_state.audio_key_counter = 0
if "messages" not in st.session_state:
    greeting = """¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar. Estamos para ayudarte a encontrar la mejor solución energética. ¿Sobre qué producto necesitas información hoy?
    
1. Calentadores Solares
2. Paneles Solares (Fuera de la red)
3. Paneles Solares (Ahorro en factura eléctrica)
4. Bombas de Agua Solares
5. Bombas de Calor para piscinas
6. Máquinas de hacer hielo
7. Hieleras

Cuéntame qué te interesa y, para darte una atención personalizada, ¿podrías indicarme tu nombre y en qué zona te encuentras?"""
    st.session_state.messages = [{"role": "assistant", "content": greeting}]

if "input_buffer" not in st.session_state:
    st.session_state.input_buffer = []
if "last_input_timestamp" not in st.session_state:
    st.session_state.last_input_timestamp = 0.0

st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**. Para obtener la mejor asesoría, realizaremos estos pasos:
    * **1. Descubrimiento:** Identificamos tus necesidades.
    * **2. Análisis Técnico:** Calculamos requerimientos.
    * **3. Especificación:** Seleccionamos equipos.
    * **4. Presupuesto:** Generamos la lista base.
    * **5. Contacto directo:** Gestión vía WhatsApp.""")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional)**")
col_img, col_cam = st.columns(2)

with col_img:
    factura_img = st.file_uploader("Sube una foto de tu factura", type=["jpg", "jpeg", "png"], key="file_factura")
with col_cam:
    factura_cam = st.camera_input("O toma una foto a la factura", key="cam_factura")

img_a_procesar = factura_img if factura_img else factura_cam
headers_api = {"Authorization": f"Bearer {API_KEY_SECRET}", "Content-Type": "application/json"}

if img_a_procesar:
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
                prompt_factura = f"[Sistema: Factura Eléctrica Procesada - Empresa: {datos.get('empresa_electrica', 'N/A')}, Consumo: {datos.get('consumo_kwh', 'N/A')} kWh, Monto: Q{datos.get('monto_factura', 'N/A')}]."
                st.session_state.input_buffer.append(prompt_factura)
                st.session_state.last_input_timestamp = time.time()
                st.success("✅ Factura inyectada en el buffer de Jarvi.")
        except Exception as e:
            st.error(f"Error técnico analizando la factura: {e}")

st.markdown("---")

# --- 5. Captura y Acumulación ---
audio_value = st.audio_input("🎤 Grabar mensaje de voz", key=f"audio_input_{st.session_state.audio_key_counter}")
text_value = st.chat_input("¿Qué solución necesitas hoy?")

if text_value:
    st.session_state.is_voice_mode = False
    st.session_state.input_buffer.append(text_value)
    st.session_state.last_input_timestamp = time.time()

if audio_value is not None:
    st.session_state.is_voice_mode = True
    if client:
        with st.spinner("Transcribiendo entrada de voz..."):
            try:
                audio_value.name = "audio.wav"
                transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_value)
                st.session_state.input_buffer.append(transcript.text)
                st.session_state.last_input_timestamp = time.time()
                st.session_state.audio_key_counter += 1
            except Exception as e:
                st.error(f"Error al transcribir audio: {e}")

prompt_consolidado = None
if st.session_state.input_buffer:
    tiempo_transcurrido = time.time() - st.session_state.last_input_timestamp
    if tiempo_transcurrido < 3.0:
        st.info(f"⏳ Consolidando datos de entrada de AISA... Esperando 3 segundos por si deseas añadir otro texto o imagen ({3.0 - tiempo_transcurrido:.1f}s)")
        time.sleep(0.5)
        st.rerun()
    else:
        prompt_consolidado = " | ".join(st.session_state.input_buffer)
        st.session_state.input_buffer = []

# --- 6. Comunicación Streaming ---
if prompt_consolidado:
    st.session_state.messages.append({"role": "user", "content": prompt_consolidado})
    with st.chat_message("user"):
        st.markdown(prompt_consolidado)
    
    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""
        
        try:
            payload = {"thread_id": st.session_state.thread_id, "message": prompt_consolidado}
            with requests.post(f"{BACKEND_URL}/chat", json=payload, headers=headers_api, stream=True, timeout=60) as response:
                if response.status_code == 200:
                    for line in response.iter_lines(decode_unicode=True):
                        if line:
                            cleaned_line = line.strip()
                            if cleaned_line.startswith("data: "):
                                try:
                                    data_json = json.loads(cleaned_line[6:])
                                    if "token" in data_json:
                                        respuesta_completa += data_json["token"]
                                        placeholder.markdown(respuesta_completa + "▌")
                                    if "error" in data_json:
                                        st.error(data_json["error"])
                                except json.JSONDecodeError:
                                    continue
                                    
                    placeholder.markdown(respuesta_completa)
                    st.session_state.messages.append({"role": "assistant", "content": respuesta_completa})
                    
                    if st.session_state.is_voice_mode and client and respuesta_completa:
                        with st.spinner("Generando síntesis de voz..."):
                            speech_response = client.audio.speech.create(
                                model="tts-1", voice="alloy", input=respuesta_completa
                            )
                            audio_buffer = io.BytesIO()
                            for chunk in speech_response.iter_bytes(chunk_size=4096):
                                audio_buffer.write(chunk)
                            audio_buffer.seek(0)
                            st.audio(audio_buffer.getvalue(), format="audio/mp3", autoplay=True)
                else:
                    st.error(f"Error del servidor backend (Código: {response.status_code}).")
        except Exception as e:
            st.error(f"Error fatal de conexión con la API: {str(e)}")
