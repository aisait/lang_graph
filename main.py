import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

st.set_page_config(page_title="Jarvi - AISA Solar", page_icon="⚡", layout="wide")

# 1. IDENTIDAD Y RESTRICCIONES (El "Cerebro")
# Instrucción explícita de NO inventar productos.
JARVI_PROMPT = """Eres Jarvi, ingeniero de preventa de AISA Solar. 
TU FUENTE DE INFORMACIÓN ES EXCLUSIVAMENTE www.aisa.com.gt.
- Si un producto o servicio NO está en www.aisa.com.gt, no lo inventes ni lo sugieras. 
- Si no sabes algo, remite al usuario a contactar a AISA Solar.
- PROHIBIDO mencionar a OpenAI o ser un modelo genérico.
- Tono: Técnico, profesional y servicial."""

if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]

# 2. TÍTULO E INSTRUCCIONES (UI)
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""
    ¡Hola! Soy Jarvi, tu ingeniero de preventa de **AISA Solar**. 
    *   **¿Buscas una solución?** Pregúntame qué buscas y te asesoraré basándome únicamente en los servicios de AISA.
    *   **Productos:** Solo te hablaré de soluciones disponibles en [www.aisa.com.gt](https://www.aisa.com.gt).
    *   **Contacto:** Si no tengo la información técnica, te indicaré cómo contactar a AISA directamente.
    """)

# 3. LÓGICA DE INICIO (Saludo automático)
if len(st.session_state.messages) == 1:
    greeting = "¡Hola! Soy Jarvi de AISA Solar. ¿Buscas una solución fotovoltaica hoy? Cuéntame qué necesitas y te ayudaré con los servicios de AISA."
    st.session_state.messages.append(AIMessage(content=greeting))

# 4. CONFIGURACIÓN (Sin selector de modelo para evitar errores)
chat_model = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

# 5. RENDERIZADO
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# 6. INTERACCIÓN
if prompt := st.chat_input("¿Buscas una solución fotovoltaica?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = chat_model.invoke(st.session_state.messages)
        st.markdown(response.content)
        st.session_state.messages.append(AIMessage(content=response.content))
