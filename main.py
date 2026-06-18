import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

st.set_page_config(page_title="Jarvi 2.0 - AISA Solar", page_icon="⚡", layout="wide")

# Prompt del sistema
JARVI_PROMPT = """Eres Jarvi, el experto técnico de AISA Solar. 
TU FUENTE DE INFORMACIÓN ES EXCLUSIVAMENTE: www.aisa.com.gt.
- No inventes productos fuera de AISA Solar.
- Si no sabes algo, remite al cliente a contactar a AISA Solar.
- PROHIBIDO decir que eres de OpenAI o un modelo genérico."""

if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]

# --- INTERFAZ ---
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

# Instrucciones (FAQs)
with st.expander("❓ ¿Cómo interactuar con Jarvi? (Haz clic aquí)", expanded=True):
    st.markdown("""
    Bienvenido a tu asistente técnico de **AISA Solar**. Para obtener la mejor asistencia, intenta lo siguiente:
    - **Proyectos:** "Necesito diseñar un sistema solar para una residencia de 500kWh al mes."
    - **Consultas Técnicas:** "¿Qué tipo de inversor recomiendan para sistemas aislados?"
    - **Contacto:** "¿Cómo puedo cotizar un proyecto directamente con AISA?"
    - **Información:** "Muéstrame los servicios disponibles en www.aisa.com.gt."
    """)

# Sidebar
with st.sidebar:
    st.title("⚙️ Configuración")
    # MODELO FIJO (Eliminamos el selector para evitar errores de 403)
    model_choice = "gpt-4o-mini"
    st.success(f"Modelo activo: {model_choice}")
    
    temp = st.slider("Creatividad", 0.0, 1.0, 0.5, 0.1)
    
    if st.button("🗑️ Reiniciar Conversación"):
        st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]
        st.rerun()

# Inicialización
chat_model = ChatOpenAI(model=model_choice, temperature=temp)

# Renderizado del chat
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# Entrada del usuario
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = chat_model.invoke(st.session_state.messages)
        st.markdown(response.content)
        st.session_state.messages.append(AIMessage(content=response.content))
