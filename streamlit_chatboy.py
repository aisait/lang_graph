import os
import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

chat_model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.5
    # Al no poner api_key aquí, LangChain buscará automáticamente 
    # la variable de entorno OPENAI_API_KEY
)

# Configuración de la app
st.set_page_config(
    page_title="Jarvi 2.0 - Agente de Soluciones Fotovoltaicas",
    page_icon="⚡"
)

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas") 
st.markdown("La ingeniería de preventa en Aisa transforma necesidades energéticas en soluciones solares personalizadas.")

# ==========================================
# 3. FORZAMOS A USAR LA NUEVA
# ==========================================
chat_model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.5,
    api_key=MI_LLAVE_NUEVA
)

# Inicializar el historial de mensajes
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar mensajes previos
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage):
        continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# Cuadro de texto para el usuario
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # Obtener la respuesta del modelo
    response = chat_model.invoke(st.session_state.messages)

    # Mostrar la respuesta
    st.session_state.messages.append(AIMessage(content=response.content))
    with st.chat_message("assistant"):
        st.markdown(response.content)
