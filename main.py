import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# 1. Configuración de la página (esto crea el diseño base)
st.set_page_config(page_title="Jarvi 2.0 - Aisa Solar", page_icon="⚡", layout="wide")

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")
st.markdown("La ingeniería de preventa en Aisa transforma necesidades energéticas en soluciones solares personalizadas.")

# 2. BARRA LATERAL (Sidebar) - Esto debe aparecer sí o sí
with st.sidebar:
    st.header("Configuración")
    model_choice = st.selectbox("Selecciona el modelo", ["gpt-4o-mini", "gpt-3.5-turbo"])
    temperature = st.slider("Temperatura", 0.0, 1.0, 0.5, 0.1)
    st.divider()
    if st.button("Borrar historial de chat"):
        st.session_state.messages = []
        st.rerun()

# 3. Inicialización del modelo
chat_model = ChatOpenAI(model=model_choice, temperature=temperature)

# 4. Inicializar historial
if "messages" not in st.session_state:
    st.session_state.messages = [
        SystemMessage(content="Eres Jarvi, experto de AISA Solar. Responde siempre con profesionalismo y enfócate en www.aisa.com.gt")
    ]

# 5. Renderizar historial (Omitiendo el SystemMessage)
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

    response = chat_model.invoke(st.session_state.messages)
    
    st.session_state.messages.append(AIMessage(content=response.content))
    with st.chat_message("assistant"):
        st.markdown(response.content)
