import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

# 1. Configuración de la app
st.set_page_config(
    page_title="Jarvi 2.0 - Agente de Soluciones Fotovoltaicas",
    page_icon="⚡"
)

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas") 
st.markdown("La ingeniería de preventa en Aisa transforma necesidades energéticas en soluciones solares personalizadas.")

# 2. Sidebar: Configuración del usuario
with st.sidebar:
    st.header("Configuración")
    model_choice = st.selectbox("Modelo de lenguaje", ["gpt-4o-mini", "gpt-3.5-turbo"])
    temp = st.slider("Temperatura", 0.0, 1.0, 0.5, 0.1)

# 3. Inicialización del modelo (Railway inyecta la API KEY automáticamente)
chat_model = ChatOpenAI(
    model=model_choice,
    temperature=temp
)

# 4. Inicializar historial de mensajes con el System Prompt optimizado
if "messages" not in st.session_state:
    st.session_state.messages = [
        SystemMessage(content="""Eres Jarvi, un experto en soluciones fotovoltaicas de AISA Solar. 
        Tu objetivo es diseñar sistemas solares personalizados, proporcionando recomendaciones técnicas 
        y financieras precisas. Enfócate en productos exclusivos del sitio www.aisa.com.gt 
        y usa un lenguaje claro y accesible.""")
    ]

# 5. Mostrar historial en pantalla
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage):
        continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# 6. Interacción con el usuario
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generar respuesta usando el historial completo
    response = chat_model.invoke(st.session_state.messages)

    # Guardar y mostrar respuesta
    st.session_state.messages.append(AIMessage(content=response.content))
    with st.chat_message("assistant"):
        st.markdown(response.content)
