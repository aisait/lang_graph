import streamlit as st
import requests
import os
import uuid
import base64
import io
import json
from openai import OpenAI

# --- 0. Configuración de Entorno (Railway - Producción) ---
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
if BACKEND_URL.endswith('/'):
    BACKEND_URL = BACKEND_URL[:-1]

API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

# Inicialización de Cliente de OpenAI (Configuración explícita)
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None
    st.error("Error crítico: OPENAI_API_KEY no configurada en el entorno.")

# --- 1. Configuración de Interfaz ---
st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# --- 2. Variables de Estado (Persistencia Completa) ---
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
2. Paneles Solares (Fuera de la red)
3. Paneles Solares (Ahorro en factura eléctrica)
4. Bombas de Agua Solares
5. Bombas de Calor para piscinas
6. Máquinas de hacer hielo
7. Hieleras

Cuéntame qué te interesa y, para darte una atención personalizada, ¿podrías indicarme tu nombre y en qué zona te encuentras?"""
    st.session_state.messages = [{"role": "assistant", "content": greeting}]

# --- 3. Título e Instrucciones UI ---
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""¡Hola! Soy Jarvi, tu ingeniero de soluciones de **AISA Solar**. Para obtener la mejor asesoría, realizaremos estos pasos:
    * **1. Descubrimiento:** Identificamos tus necesidades.
    * **2. Análisis Técnico:** Calculamos requerimientos.
    * **3. Especificación:** Seleccionamos equipos.
    * **4. Presupuesto:** Generamos la lista base.
    * **5. Contacto directo:** Gestión vía WhatsApp.""")

# Renderizado de historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 4. Lógica Multimodal (Captura de Factura) ---
st.markdown("---")
st.write("📸 **Cargar Factura Eléctrica (Opcional)**")
col_img, col_cam = st.columns(2)

with col_img:
    factura_img = st.file_uploader("Sube una foto de tu factura", type=["jpg", "jpeg", "png"], key="file_factura")
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
                timeout=(3.0, 30.0) # 3 segundos enlace inicial, 30 segundos tiempo máximo de ejecución de visión
            )
            
            if res.status_code == 200:
                datos = res.json().get("extracted_data", {})
                st.session_state.factura_procesada = True
                prompt_factura = f"He subido mi factura eléctrica. Datos detectados: Empresa: {datos.get('empresa_electrica', 'N/A')}, Consumo: {datos.get('consumo_kwh', 'N/A')} kWh, Monto: Q{datos.get('monto_factura', 'N/A')}."
                st.session_state.pending_prompt = prompt_factura
                st.success("✅ Factura analizada correctamente.")
                st.rerun()
            else:
                st.error(f"Fallo al procesar la factura en el servidor (Código {res.status_code}).")
        except Exception as e:
            st.error(f"Error técnico analizando la factura: {e}")

st.markdown("---")

# --- 5. Entrada de Usuario (Voz y Texto) ---
audio_value = st.audio_input("🎤 Grabar mensaje de voz", key=f"audio_input_{st.session_state.audio_key_counter}")
text_value = st.chat_input("¿Qué solución necesitas hoy?")

prompt = None
if text_value:
    st.session_state.is_voice_mode = False
    prompt = text_value
elif audio_value is not None:
    st.session_state.is_voice_mode = True
    if client:
        with st.spinner("Transcribiendo mensaje de voz..."):
            try:
                audio_value.name = "audio.wav"
                transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_value)
                st.session_state.pending_prompt = transcript.text
                st.session_state.audio_key_counter += 1
                st.rerun()
            except Exception as e:
                st.error(f"Error al transcribir audio: {e}")
    else:
        st.error("Error: Cliente OpenAI no inicializado.")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None 

# --- 6. Comunicación Streaming con el Backend (Lógica de Chat Activa) ---
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        placeholder = st.empty()
        respuesta_completa = ""
        contexto_tecnico = {}
        
        try:
            payload = {"thread_id": st.session_state.thread_id, "message": prompt}
            
            # Control estricto de timeout de ingeniería: 3 segundos para el handshake inicial, 15 de lectura completa
            with requests.post(f"{BACKEND_URL}/chat", json=payload, headers=headers_api, stream=True, timeout=(3.0, 15.0)) as response:
                if response.status_code == 200:
                    # El iterador de líneas se procesa bajo un búfer inmediato sin acumulación oculta
                    for line in response.iter_lines(decode_unicode=True):
                        if line:
                            cleaned_line = line.strip()
                            if cleaned_line.startswith("data: "):
                                try:
                                    data_json = json.loads(cleaned_line[6:])
                                    
                                    # Inyección inmediata del token en la UI eliminando el estado colgado/mudo
                                    if "token" in data_json:
                                        respuesta_completa += data_json["token"]
                                        placeholder.markdown(respuesta_completa + "▌")
                                    
                                    if "contexto_tecnico" in data_json:
                                        contexto_tecnico = data_json["contexto_tecnico"]
                                    
                                    if "error" in data_json:
                                        st.error(data_json["error"])
                                except json.JSONDecodeError:
                                    continue # Resiliencia ante fragmentación parcial de paquetes de red
                                    
                    # Fijación de texto finalizado
                    placeholder.markdown(respuesta_completa)
                    st.session_state.messages.append({"role": "assistant", "content": respuesta_completa})
                    
                    # Ejecución del sintetizador de audio sobre el bloque unificado
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
                    st.error(f"Error del servidor backend (Código: {response.status_code}). Verifica los logs de la API.")
        except requests.exceptions.Timeout:
            st.error("⏱️ Error de Red: Excedido el límite de conexión de 3 segundos con el Core de Ingeniería.")
        except Exception as e:
            st.error(f"Error fatal de conexión con la API: {str(e)}")
