# main.py
import streamlit as st
import io
import uuid
import traceback
from openai import OpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

# Importación de la Arquitectura Fragmentada
import config
from audit import notificar_error_runtime
from agent_graph import inicializar_motor_jarvi

# Cliente de Inferencia Exclusivo de Media (Voz/Facturas)
client_openai = OpenAI(api_key=config.os.getenv("OPENAI_API_KEY"))

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# Inicialización Asíncrona del Grafo Compilado
jarvi_graph = inicializar_motor_jarvi()

# Gestión Segura del Estado de la Sesión en Streamlit
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
    greeting = "¡Hola! 👋 Soy Jarvi, tu asesor técnico de AISA Solar. ¿Sobre qué sistema necesitas ingeniería hoy?\n1. Calentadores\n2. Sistemas Aislados\n3. Sistemas On-Grid / Ahorro\n\nPor favor, indícame tu nombre y departamento."
    st.session_state.messages = [AIMessage(content=greeting)]
    
    config_graph = {"configurable": {"thread_id": st.session_state.thread_id}}
    jarvi_graph.update_state(config_graph, {
        "messages": [AIMessage(content=greeting)],
        "contexto_tecnico": {"ciudad": None, "empresa_electrica": None, "tarifa_base_gtq": None, "topologia": None, "calculo_carga_completado": False, "requiere_auditoria_electrica": False}
    })

st.title("Jarvi ⚡ Asesor Técnico de Ingeniería - AISA Solar")

# Renderizado de Historial Conversacional Estático de Alta Velocidad
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage):
        st.chat_message("assistant").markdown(msg.content)
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage):
        st.chat_message("system").markdown(f"⚙️ Log de Auditoría: {msg.content}")

# Captura de Eventos Multimodales (Entrada de Facturas)
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

# Captura de Flujo Conversacional
audio_value = st.audio_input("🎤 Mensaje de Voz Comercial", key=f"audio_input_{st.session_state.audio_key_counter}")
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
        with st.spinner("Consultado en tiempo real a equipo de Ingeniería especializado de AISA Solar..."):
            try:
                config_graph = {"configurable": {"thread_id": st.session_state.thread_id}}
                response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=prompt)]}, config_graph)
                
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
                    estado_actual = jarvi_graph.get_state(config_graph).values.get("contexto_tecnico", {})
                except:
                    estado_actual = "Error al leer estado"
                
                snapshot = {"thread_id": st.session_state.thread_id, "contexto": estado_actual}
                notificar_error_runtime(e, tb_str, snapshot, prompt)
                st.error("🚨 Interrupción en el procesamiento de su solicitud. El equipo técnico ya fue notificado.")
