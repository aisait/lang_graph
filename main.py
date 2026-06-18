import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
import os

# Configuración de página
st.set_page_config(page_title="Jarvi 2.0 - AISA Solar", page_icon="⚡", layout="wide")

# 1. IDENTIDAD INMUTABLE (Prompt Engineering)
JARVI_SYSTEM_PROMPT = """Eres Jarvi, el experto técnico de AISA Solar (www.aisa.com.gt). 
Tu misión es diseñar sistemas solares y responder consultas técnicas. 
- Fuente de verdad: www.aisa.com.gt.
- Si no conoces un dato, remite al usuario a contactar a AISA.
- PROHIBIDO decir que eres de OpenAI o un modelo genérico.
- Eres un ingeniero de preventa profesional y cercano."""

if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_SYSTEM_PROMPT)]

# 2. INTERFAZ: Título e Instrucciones
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

# Instrucciones visibles para el usuario
with st.expander("ℹ️ ¿Cómo puedo ayudarte?"):
    st.markdown("""
    Soy Jarvi, tu ingeniero de preventa en **AISA Solar**. Estoy aquí para transformar tus necesidades en soluciones energéticas. 
    **Puedes preguntarme sobre:**
    * **Dimensionamiento:** "¿Qué sistema necesito para una casa con consumo de 500kWh?"
    * **Productos:** "¿Tienen paneles solares de X potencia?"
    * **Técnica:** "¿Qué diferencia hay entre un inversor de cadena y un microinversor?"
    * **Referencia:** "¿Cuál es la dirección de AISA o cómo contacto ventas?"
    
    *Para obtener mejores resultados, intenta incluir datos como tu ubicación o tu factura eléctrica mensual.*
    """)

# 3. BARRA LATERAL (Configuración)
with st.sidebar:
    st.header("Configuración")
    # Restringido estrictamente a lo que tu cuenta permite (gpt-4o-mini)
    model_choice = "gpt-4o-mini"
    st.info(f"Modelo activo: {model_choice}")
    temp = st.slider("Creatividad", 0.0, 1.0, 0.5, 0.1)
    
    if st.button("🗑️ Reiniciar Conversación"):
        st.session_state.messages = [SystemMessage(content=JARVI_SYSTEM_PROMPT)]
        st.rerun()

# 4. LÓGICA DE EJECUCIÓN
# Verificar si la API KEY existe
if not os.environ.get("OPENAI_API_KEY"):
    st.error("Error: API Key no configurada en Railway. Por favor, revisa tus variables de entorno.")
    st.stop()

chat_model = ChatOpenAI(model=model_choice, temperature=temp)

# Renderizado
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

    with st.chat_message("assistant"):
        try:
            response = chat_model.invoke(st.session_state.messages)
            st.markdown(response.content)
            st.session_state.messages.append(AIMessage(content=response.content))
        except Exception as e:
            st.error(f"Ocurrió un error técnico: {e}")
