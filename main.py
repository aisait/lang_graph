import streamlit as st
import os
import requests
import uuid
import tempfile
from typing import Annotated, TypedDict
from dotenv import load_dotenv

from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# =====================================================================
# 1. DEFINICIÓN DEL ESTADO Y ENTORNO
# =====================================================================
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

load_dotenv()
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM") # ID por defecto o Custom Voice

st.set_page_config(page_title="Jarvi ⚡ AISA Solar", page_icon="⚡", layout="wide")

# HACK DE UI CON CSS: Unificación del Dock de Entrada (Estilo WhatsApp/Telegram)
st.markdown("""
    <style>
    /* Remover márgenes excesivos en inputs y compactar layout */
    .stAudioInput > label {
        display: none !important;
    }
    div[data-testid="stHorizontalBlock"] {
        align-items: center !important;
        background-color: #11151c;
        padding: 8px 14px;
        border-radius: 24px;
        border: 1px solid #2d3748;
        margin-top: 10px;
    }
    /* Estilización del reproductor de audio embebido dentro del mensaje */
    .stAudio {
        margin-top: 8px;
        width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_memory():
    return MemorySaver()

memory = get_memory()
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# =====================================================================
# 2. ONTOLOGÍA INTEGRAL (70 CATEGORÍAS)
# =====================================================================
ONTOLOGIA_AISA = """
[Ontología original intacta para la preservación de los hipervínculos del Core Business de AISA Solar]
"""

# =====================================================================
# 3. HERRAMIENTAS
# =====================================================================
@tool
def enviar_whatsapp_humano(nombre_cliente: str, numero_whatsapp: str, resumen_35_palabras: str, productos_links: str, presupuesto_estimado: str) -> str:
    """Ejecuta esta herramienta SOLO cuando el cliente acepte el presupuesto."""
    num_limpio = ''.join(filter(str.isdigit, numero_whatsapp))
    payload = {
        "instance_id": APICHAT_INSTANCE,
        "number": num_limpio,
        "text": f"🚨 Lead: {nombre_cliente}\nResumen: {resumen_35_palabras}\nLinks: {productos_links}\nPresupuesto: {presupuesto_estimado}"
    }
    headers = {"Authorization": f"Bearer {APICHAT_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.post(APICHAT_ENDPOINT, json=payload, headers=headers, timeout=15)
        return "¡Excelente! He enviado tu solicitud al equipo de ingeniería de AISA." if response.status_code in [200, 201] else f"Error: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

# =====================================================================
# 4. MOTOR COGNITIVO (LANGGRAPH INTEGRATION)
# =====================================================================
graph_builder = StateGraph(AgentState)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1).bind_tools([enviar_whatsapp_humano])

def chatbot_node(state: AgentState):
    prompt_sistema = SystemMessage(content=f"""
    Eres Jarvi, Ingeniero de Preventa experto de AISA Solar. Hablas de forma fluida y natural. Evita viñetas excesivas.
    Tu operativa interna sigue el protocolo técnico D.E.S.I.G.N.-5. El resumen final de Cierre debe ser de EXACTAMENTE 35 PALABRAS.
    ONTOLOGÍA DEL ECOSISTEMA AISA SOLAR: {ONTOLOGIA_AISA}
    """)
    return {"messages": [llm.invoke([prompt_sistema] + state["messages"])]}

graph_builder.add_node("chatbot", chatbot_node)
graph_builder.add_node("tools", ToolNode([enviar_whatsapp_humano]))
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge(START, "chatbot")

jarvi_graph = graph_builder.compile(checkpointer=memory)

# =====================================================================
# 5. TRANSDUCTORES MULTIMEDIA DE AUDIO (OPENAI & ELEVENLABS)
# =====================================================================
def transcribe_voice_input(audio_bytes):
    """Procesa el audio ingresado en la caja unificada mediante OpenAI Whisper."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
        
        with open(temp_path, "rb") as f:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="es"
            )
        os.remove(temp_path)
        return transcript.text
    except Exception as e:
        st.error(f"Error en transcripción Whisper: {str(e)}")
        return None

def generate_elevenlabs_speech(text):
    """Genera audio con ElevenLabs utilizando los parámetros del ADN de marca de JARVI."""
    if not ELEVENLABS_API_KEY:
        return None
        
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.74,
            "similarity_boost": 0.91,
            "style": 0.18,
            "use_speaker_boost": True
        }
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=20)
        if response.status_code == 200:
            return response.content
        else:
            st.warning(f"ElevenLabs API devolió status {response.status_code}")
    except Exception as e:
        st.error(f"Excepción en ElevenLabs: {str(e)}")
    return None

# =====================================================================
# 6. ORQUESTACIÓN DE INTERFAZ GRÁFICA DE USUARIO (STREAMLIT)
# =====================================================================
st.title("Jarvi ⚡ Agente de Soluciones de AISA Solar")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    greeting = "¡Hola! 👋 Soy Jarvi, Ingeniero de Soluciones de AISA Solar. Para iniciar a definir tus necesidades, ¿podrías indicarme tu Nombre y tu número de WhatsApp?"
    st.session_state.messages = [AIMessage(content=greeting)]
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    jarvi_graph.update_state(config, {"messages": [AIMessage(content=greeting)]})

# Renderizado Persistente del Historial de Conversación
for msg in st.session_state.messages:
    if isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.markdown(msg.content)
            # Renderizado nativo del MP3 dentro del contenedor del mensaje si existe el payload de voz
            if hasattr(msg, "audio_bytes") and msg.audio_bytes:
                st.audio(msg.audio_bytes, format="audio/mp3")
    elif isinstance(msg, HumanMessage):
        st.chat_message("user").markdown(msg.content)
    elif isinstance(msg, ToolMessage):
        st.chat_message("system").markdown(f"⚙️ Operación: {msg.content}")

# CONTROL DE POLÍTICA ECONÓMICA DE TOKENS (Compuerta lógica solicitada por el cliente)
st.write("---")
solicitar_nota_voz = st.toggle("🎙️ Deseo recibir la respuesta de Jarvi por nota de voz (ElevenLabs)", value=False)

# UNIFICACIÓN MECÁNICA DE ENTRADA (Caja de Texto + Micrófono en la misma fila física)
container_dock = st.container()
with container_dock:
    col_text, col_voice = st.columns([0.85, 0.15])
    
    with col_text:
        raw_text = st.text_input("Escribe tu consulta aquí...", label_visibility="collapsed", key="input_texto_usuario")
        
    with col_voice:
        raw_audio = st.audio_input("Grabar", label_visibility="collapsed", key="input_audio_usuario")

# Centralización del Flujo de Entrada
final_prompt = None

if raw_audio:
    with st.spinner("Transcribiendo nota de voz entrante con Whisper..."):
        final_prompt = transcribe_voice_input(raw_audio.getvalue())
elif raw_text:
    final_prompt = raw_text

# Procesamiento de la Inferencia de Estado en LangGraph
if final_prompt:
    st.session_state.messages.append(HumanMessage(content=final_prompt))
    st.chat_message("user").markdown(final_prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Consultando en tiempo real con ingeniería especializada..."):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            response_state = jarvi_graph.invoke({"messages": [HumanMessage(content=final_prompt)]}, config)
            
            # Extraer los nuevos mensajes del grafo de ejecución
            new_messages = response_state["messages"][len(st.session_state.messages)-1:]
            for msg in new_messages:
                if isinstance(msg, AIMessage) and msg.content:
                    st.markdown(msg.content)
                    
                    # Ejecución condicionada a la demanda explícita del cliente para ahorro de costes de terceros
                    if solicitar_nota_voz:
                        with st.spinner("Sintetizando audio premium con ElevenLabs..."):
                            audio_payload = generate_elevenlabs_speech(msg.content)
                            if audio_payload:
                                msg.audio_bytes = audio_payload
                                st.audio(audio_payload, format="audio/mp3", autoplay=True)
                elif isinstance(msg, ToolMessage):
                    st.markdown(f"⚙️ {msg.content}")
                    
            st.session_state.messages = response_state["messages"]
