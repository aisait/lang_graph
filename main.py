import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# Configuración de la página
st.set_page_config(page_title="Jarvi 2.0 - Aisa Solar", page_icon="⚡", layout="wide")

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

# Definición del SYSTEM_PROMPT fuera de cualquier lógica condicional
# para asegurar que siempre esté disponible.
JARVI_SYSTEM_PROMPT = """Eres Jarvi, un experto en soluciones fotovoltaicas de AISA Solar (www.aisa.com.gt). 
Tu misión es diseñar sistemas solares personalizados, optimizar técnica y financieramente los proyectos. 
Responde siempre como Jarvi, el experto técnico de AISA Solar. 
NO menciones a OpenAI ni digas que eres un modelo de lenguaje genérico."""

# Inicializar historial en session_state
if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_SYSTEM_PROMPT)]

# Sidebar para control
with st.sidebar:
    model_choice = st.selectbox("Modelo", ["gpt-4o-mini", "gpt-3.5-turbo"])
    if st.button("Reiniciar Chat"):
        st.session_state.messages = [SystemMessage(content=JARVI_SYSTEM_PROMPT)]
        st.rerun()

# Inicializar modelo
chat_model = ChatOpenAI(model=model_choice, temperature=0.5)

# Mostrar historial
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# Interacción
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # El modelo debe recibir la lista completa, incluyendo el SystemMessage inicial
    response = chat_model.invoke(st.session_state.messages)
    
    st.session_state.messages.append(AIMessage(content=response.content))
    with st.chat_message("assistant"):
        st.markdown(response.content)
