import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

st.set_page_config(page_title="Jarvi 2.0 - AISA Solar", page_icon="⚡", layout="wide")

JARVI_PROMPT = """Eres Jarvi, el experto técnico de AISA Solar. 
TU FUENTE DE INFORMACIÓN ES EXCLUSIVAMENTE: www.aisa.com.gt.
- No inventes productos fuera de AISA Solar.
- Si no sabes algo, remite al cliente a contactar a AISA Solar.
- PROHIBIDO decir que eres de OpenAI o un modelo genérico."""

if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]

with st.sidebar:
    st.title("⚙️ Configuración")
    # AQUÍ ESTÁN LOS ÚNICOS MODELOS PERMITIDOS SEGÚN TU SCREENSHOT
    model_choice = st.selectbox("Modelo", ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"])
    temp = st.slider("Temperatura", 0.0, 1.0, 0.5, 0.1)
    
    if st.button("🗑️ Reiniciar Conversación"):
        st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]
        st.rerun()

# Inicialización del modelo con el modelo seleccionado
chat_model = ChatOpenAI(model=model_choice, temperature=temp)

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = chat_model.invoke(st.session_state.messages)
        st.markdown(response.content)
        st.session_state.messages.append(AIMessage(content=response.content))
