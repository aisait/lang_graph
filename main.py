# main.py
import streamlit as st
import io
import uuid
import traceback
import re  # CORRECCIÓN: Importación requerida para evitar fallo en auditoría por NameError
import time  # CORRECCIÓN: Requerido para la ventana de espera de 60 segundos

from openai import OpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

import config
from audit import notificar_error_runtime
from agent_graph import inicializar_motor_jarvi

client_openai = OpenAI(api_key=config.os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")
jarvi_graph = inicializar_motor_jarvi()

# Capa de Aislamiento del Session State de Streamlit
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

config_graph = {"configurable": {"thread_id": st.session_state.thread_id}}

if "messages" not in st.session_state:
    # CORRECCIÓN: Formato exacto solicitado para el mensaje de bienvenida y listado numérico
    greeting = (
        "¡Hola! 👋 Soy Jarvi, su asesor técnico de AISA Solar. Muchas gracias por contactarnos!\n\n"
        "Nos ponemos a su disposicon con nuestros productos.\n\n"
        "1.\tCalentadores solares\n"
        "2.\tPaneles solares Atados a la Red para ahorro en su factura\n"
        "3.\tSistemas de paneles solares aislados (para lugares sin energía eléctrica)\n"
        "4.\tBombas de agua solares\n"
        "5.\tBombas de calor para piscinas\n"
        "6.\tMáquinas de hacer hielo (Ice Maker)\n"
        "7.\tHieleras, refrigeradores y congeladores\n\n"
        "¿Sobre cuál de estos productos necesita información? Favor indicar Nombre y WhatsApp para cotizarle..."
    )
    st.session_state.messages = [AIMessage(content=greeting)]
    
    jarvi_graph.update_state(config_graph, {
        "messages": [AIMessage(content=greeting)],
        "contexto_tecnico": {
            "ciudad": None, "empresa_electrica": None, "tarifa_base_gtq": None, "topologia": None, 
            "calculo_carga_completado": False, "requiere_auditoria_electrica": False,
            "nombre_usuario": "Prospecto Nuevo", "whatsapp_normalizado": "No Provisto"
        }
    })

st.title("Jarvi ⚡ Asesor Técnico de Ingeniería - AISA Solar")

for msg in st.session_state.messages:
    if isinstance(msg, AIMessage):
        st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage):
        st.chat_message("system").markdown(f"⚙️ Log de Auditoría: {msg.content}")

st.markdown("---")
factura_img = st.file_uploader("📸 Carga de Factura de Distribución Eléctrica", type=["jpg", "jpeg", "png"])
if factura_img and not st.session_state.factura_procesada:
    with st.spinner("Análisis de visión artificial en ejecución..."):
        try:
            import json, base64
            base64_image = base64.b64encode(factura_img.getvalue()).decode('utf-8')
            response = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [{"type": "text", "text": "Extrae de la factura: empresa_electrica, consumo_kwh, monto_factura en JSON."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
                response_format={"type": "json_object"}
            )
            datos = json.loads(response.choices[0].message.content)
            st.session_state.factura_procesada = True
            st.session_state.pending_prompt = f"Factura cargada. Datos extraídos de forma segura: {datos}"
            st.rerun()
        except Exception as e:
            st.error(f"Fallo en la lectura del archivo de imagen: {e}")

audio_value = st.audio_input("🎤 Enviar nota de voz", key=f"audio_input_{st.session_state.audio_key_counter}")
text_value = st.chat_input("Consulte con el ingeniero de preventa aquí...")

prompt = text_value
if audio_value:
    st.session_state.is_voice_mode = True
    with st.spinner("Procesando señal de audio..."):
        try:
            audio_value.name = "audio.wav"
            transcript = client_openai.audio.transcriptions.create(model="whisper-1", file=audio_value)
            prompt = transcript.text
            st.session_state.audio_key_counter += 1
        except Exception as e:
            st.error(f"Fallo de transcripción de audio: {e}")

if st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

if prompt:
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").markdown(prompt)
    
    with st.chat_message("assistant"):
        try:
            # Recuperación del estado técnico previo
            estado_previo = jarvi_graph.get_state(config_graph).values
            ctx_actual = estado_previo.get("contexto_tecnico", {})
            
            nombre_lead = ctx_actual.get("nombre_usuario", "Nuevo Lead")
            
            # Interceptación heurística preventiva para mitigar el Naming Lag en la primera traza
            if nombre_lead == "Prospecto Nuevo":
                match = re.search(r"(?:soy|llamo|nombre es)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", prompt, re.IGNORECASE)
                if match:
                    nombre_lead = match.group(1).title()

                # CORRECCIÓN: Ventana de espera exacta de 20 segundos antes de generar la respuesta inicial de Jarvi
                with st.spinner("Por favor, espere un momento se esta procesando su solicitud...."):
                    time.sleep(20)

            # Configuración de observabilidad inyectada dinámicamente
            config_ejecucion = {
                "configurable": {"thread_id": st.session_state.thread_id},
                "run_name": f"Lead: {nombre_lead}",
                "tags": ["aisa-produccion-solar"]
            }
            
            with st.spinner("Consultando en tiempo real a equipo de Ingeniería especializado de AISA Solar..."):
                response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=prompt)]}, config=config_ejecucion)
            
            new_messages = response_state["messages"][len(st.session_state.messages)-1:]
            for msg in new_messages:
                if isinstance(msg, AIMessage) and msg.content:
                    st.markdown(msg.content)
                    if st.session_state.is_voice_mode:
                        speech = client_openai.audio.speech.create(model="tts-1", voice="alloy", input=msg.content)
                        audio_buffer = io.BytesIO()
                        for chunk in speech.iter_bytes(chunk_size=4096): audio_buffer.write(chunk)
                        audio_buffer.seek(0)
                        st.audio(audio_buffer, format="audio/mp3", autoplay=True)
                elif isinstance(msg, ToolMessage):
                    st.markdown(f"⚙️ {msg.content}")
                    
            st.session_state.messages = response_state["messages"]
        except Exception as e:
            tb_str = traceback.format_exc()
            try:
                estado_error = jarvi_graph.get_state(config_graph).values.get("contexto_tecnico", {})
            except:
                estado_error = "Error crítico de lectura de estado"
            
            snapshot = {"thread_id": st.session_state.thread_id, "contexto": estado_error}
            notificar_error_runtime(e, tb_str, snapshot, prompt)
            st.error("🚨 Interrupción en el procesamiento de su solicitud. El equipo técnico ya fue notificado.")
