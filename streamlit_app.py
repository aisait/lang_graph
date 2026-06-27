import streamlit as st
import requests
import os
import uuid

# Configuración de la página
st.set_page_config(page_title="Jarvi - AISA Solar", page_icon="☀️", layout="centered")

# --- Variables de Entorno Seguras ---
# En Railway, esta variable debe apuntar al dominio público de tu API (ej. https://api-aisa.up.railway.app)
API_URL = os.getenv("API_URL", "http://localhost:8000")

# --- Gestión de Estado de Interfaz ---
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4()) # ID único por sesión web

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Renderizado de UI ---
st.title("☀️ Jarvi - Preventa Técnica AISA Solar")
st.markdown("Consultor experto en sistemas fotovoltaicos On-Grid y Off-Grid.")

# Mostrar historial de chat
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Lógica de Interacción ---
if prompt := st.chat_input("Ingresa tu consulta sobre energía solar..."):
    # 1. Imprimir mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Orquestar llamada al Core Cognitivo (API REST)
    with st.chat_message("assistant"):
        with st.spinner("Analizando topología y requerimientos..."):
            try:
                payload = {"thread_id": st.session_state.thread_id, "message": prompt}
                # Timeout alto porque el Agente puede estar buscando en RAG o ejecutando Tools
                response = requests.post(f"{API_URL}/chat", json=payload, timeout=60)
                response.raise_for_status() # Lanza excepción si el status no es 200
                
                data = response.json()
                respuesta_ia = data.get("response", "Lo siento, hubo un error procesando la ontología.")
                
                st.markdown(respuesta_ia)
                st.session_state.messages.append({"role": "assistant", "content": respuesta_ia})
                
            except requests.exceptions.ConnectionError:
                st.error("Error 502/503: No se pudo contactar al API Core. Verifica que el servicio API esté 'Healthy' en Railway.")
            except requests.exceptions.Timeout:
                st.error("Error 504: El agente cognitivo tardó demasiado en responder.")
            except Exception as e:
                st.error(f"Error interno: {str(e)}")
