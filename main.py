import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

st.set_page_config(page_title="Jarvi - AISA Solar", page_icon="⚡", layout="wide")

# 1. IDENTIDAD Y RESTRICCIONES
JARVI_PROMPT = """Eres Jarvi, ingeniero de preventa de AISA Solar. 
TU FUENTE DE INFORMACIÓN ES EXCLUSIVAMENTE www.aisa.com.gt.
- Si un producto o servicio NO está en www.aisa.com.gt, no lo inventes ni lo sugieras. 
- Si no sabes algo, remite al usuario a contactar a AISA Solar.
- PROHIBIDO mencionar a OpenAI o ser un modelo genérico.
- PROHIBIDO mencionar a otras marcas que no sean SOLAR.
- Tono: Técnico, profesional y servicial."""

if "messages" not in st.session_state:
    st.session_state.messages = [SystemMessage(content=JARVI_PROMPT)]

# 2. TÍTULO E INSTRUCCIONES (UI)
st.title("Jarvi ⚡ Agente de Soluciones Fotovoltaicas")

with st.expander("ℹ️ ¿Cómo usar Jarvi?"):
    st.markdown("""
    ¡Hola! Soy Jarvi, tu ingeniero de preventa de **AISA Solar**. Para obtener la mejor asesoría, sigue estos pasos:
    * **Describe tu necesidad Sistema Atado a la Red o aislado de la  red eléctrica Nacional:** Explícame tu proyecto, consumo energético mensual o ubicación para darte una solución a medida.
    * **Consulta sobre productos:** Pregúntame específicamente por la disponibilidad y características técnicas de equipos en [www.aisa.com.gt](https://www.aisa.com.gt).
    * **Sé preciso:** Evita consultas genéricas; cuanto más detalle técnico me des, mejor podré recomendarte las soluciones de AISA.
    * **Contacto directo:** Si necesitas una cotización formal o atención personalizada, te trsladare vía WhatsApp con el equipo de AISA.
    """)

# 3. LÓGICA DE INICIO (Saludo automático)
if len(st.session_state.messages) == 1:
    greeting = "¡Hola! 👋 Soy Jarvi de AISA Solar, tu asistente inteligente. Para brindarte una atención personalizada, ¿podrías compartirme tu Nombre y Apellido? Y, si deseas recibir por WhatsApp la información y recomendaciones que conversemos, también puedes compartirme tu número. Cuéntame qué necesitas hoy y con gusto te ayudaré a encontrar la mejor solución de AISA."
    st.session_state.messages.append(AIMessage(content=greeting))

# 4. CONFIGURACIÓN
chat_model = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)

# 5. RENDERIZADO
for msg in st.session_state.messages:
    if isinstance(msg, SystemMessage): continue
    role = "assistant" if isinstance(msg, AIMessage) else "user"
    with st.chat_message(role):
        st.markdown(msg.content)

# 6. INTERACCIÓN
if prompt := st.chat_input("¿Qué sistema de AISA Solar necesitas: Agua, Energía, Respaldo o Climatización?"):
    st.session_state.messages.append(HumanMessage(content=prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = chat_model.invoke(st.session_state.messages)
        st.markdown(response.content)
        st.session_state.messages.append(AIMessage(content=response.content))
