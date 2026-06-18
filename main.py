import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# Configuración de la página
st.set_page_config(page_title="Jarvi 2.0 - Aisa Solar", page_icon="⚡")
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

# 1. Definimos el System Prompt de forma clara
SYSTEM_PROMPT = """Eres Jarvi, un experto en soluciones fotovoltaicas de AISA Solar (www.aisa.com.gt). 
Tu misión es diseñar sistemas solares personalizados, optimizar técnica y financieramente los proyectos, 
y responder dudas de clientes. Si te preguntan quién eres, responde que eres Jarvi, el experto 
técnico de AISA Solar. No menciones a OpenAI ni digas que eres un modelo de lenguaje genérico."""

# 2. Inicializar historial si no existe
if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=SYSTEM_PROMPT)]

# 3. Sidebar para configuración
with st.sidebar:
    model_choice = st.selectbox("Modelo", ["gpt-4o-mini", "gpt-3.5-turbo"])
    temp = st.slider("Temperatura", 0.0, 1.0, 0.5, 0.1)

# 4. Inicializar modelo
chat_model = ChatOpenAI(model=model_choice, temperature=temp)

# 5. Renderizar historial (excluyendo el SystemMessage para el usuario)
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# 6. Interacción
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # El modelo invoca todo el historial, incluyendo el SystemMessage inicial
    response = chat_model.invoke(st.session_state.messages)
    
    st.session_state.messages.append(AIMessage(content=response.content))
    with st.chat_message("assistant"):
        st.markdown(response.content)
