import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

st.set_page_config(page_title="Jarvi 2.0", page_icon="⚡", layout="wide")

st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

# 1. Definición del rol estricto
# Esto fuerza al modelo a ser Jarvi y a ignorar cualquier identidad de OpenAI
SYSTEM_INSTRUCTION = """Eres Jarvi, el experto técnico de AISA Solar (www.aisa.com.gt). 
Tu ÚNICA identidad es Jarvi. Si te preguntan quién eres, debes decir que eres Jarvi de AISA Solar. 
Prohibido decir que eres un asistente de OpenAI o un modelo de lenguaje genérico. 
Si el usuario menciona 'Jarvi', reconoce tu nombre inmediatamente."""

# 2. Inicialización de sesión con el sistema forzado
if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=SYSTEM_INSTRUCTION)]

# 3. Sidebar funcional
with st.sidebar:
    model_choice = st.selectbox("Modelo", ["gpt-4o-mini", "gpt-3.5-turbo"])
    if st.button("Reiniciar Conversación"):
        st.session_state.messages = [SystemMessage(content=SYSTEM_INSTRUCTION)]
        st.rerun()

# 4. Inicializar modelo
chat_model = ChatOpenAI(model=model_choice, temperature=0.5)

# 5. Renderizado
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
