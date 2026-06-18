import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# 1. Configuración de página
st.set_page_config(page_title="Jarvi 2.0 - AISA Solar", page_icon="⚡", layout="wide")

# 2. Identidad Inmutable
JARVI_PROMPT = """Eres Jarvi, el Agente Experto de AISA Solar. 
TU FUENTE DE INFORMACIÓN EXCLUSIVA Y REFERENCIA ES: www.aisa.com.gt.
- Solo debes recomendar productos y soluciones disponibles en AISA Solar.
- PROHIBIDO hablar de OpenAI, no eres un asistente genérico.
- Si te preguntan quién eres, responde siempre: 'Soy Jarvi, el experto técnico de AISA Solar'.
- Si no sabes algo, remite al cliente a consultar www.aisa.com.gt."""

# 3. Inicialización del Historial
if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]

# 4. Sidebar (Forzado para que aparezca)
with st.sidebar:
    st.title("⚙️ Panel de Control")
    # Solo ofrecemos el modelo que TÚ confirmaste en tu screenshot
    model_choice = st.selectbox("Modelo", ["gpt-4o-mini"])
    temp = st.slider("Temperatura", 0.0, 1.0, 0.5, 0.1)
    
    if st.button("🗑️ Reiniciar Conversación"):
        st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]
        st.rerun()

# 5. Inicialización de modelo
chat_model = ChatOpenAI(model=model_choice, temperature=temp)

# 6. Renderizado de Interfaz
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# 7. Lógica de Interacción
if prompt := st.chat_input("¿Qué buscas lograr con la energía solar?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # Se envía toda la lista, incluyendo el SystemMessage que definimos arriba
        response = chat_model.invoke(st.session_state.messages)
        st.markdown(response.content)
        st.session_state.messages.append(AIMessage(content=response.content))
