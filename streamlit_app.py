import streamlit as st
import requests
import os
import uuid
from config import N8N_WEBHOOK_URL

st.set_page_config(page_title="Jarvi - AISA Solar", page_icon="☀️", layout="centered")

# --- Estado de Interfaz ---
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("☀️ Jarvi - Preventa Técnica AISA Solar")

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Lógica de Interacción (n8n Webhook) ---
if prompt := st.chat_input("Ingresa tu consulta sobre energía solar..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Conectando con el flujo n8n..."):
            try:
                payload = {
                    "thread_id": st.session_state.thread_id, 
                    "message": prompt
                }
                
                # Comunicación directa al webhook de n8n
                response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=60)
                response.raise_for_status()
                
                data = response.json()
                # Ajusta esta clave según la salida de tu nodo final en n8n
                respuesta_ia = data.get("output", data.get("response", "Respuesta recibida."))
                
                st.markdown(respuesta_ia)
                st.session_state.messages.append({"role": "assistant", "content": respuesta_ia})
                
            except Exception as e:
                st.error(f"Error de conexión con n8n: {str(e)}")
