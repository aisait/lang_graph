import streamlit as st
import requests
import os
import uuid
# Importamos la variable saneada desde tu configuración centralizada
from config import API_URL

# Configuración de la página
st.set_page_config(page_title="Jarvi - AISA Solar", page_icon="☀️", layout="centered")

# --- Variables de Entorno Seguras ---
# INYECCIÓN QUIRÚRGICA: Recuperación del Bearer Token maestro para interoperabilidad segura
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")

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
                
                # INYECCIÓN QUIRÚRGICA: Cabeceras con estándar global M2M (Machine-to-Machine)
                headers = {
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                }
                
                # Timeout alto para procesos RAG/Tools
                # Usamos la API_URL purificada importada desde config.py
                response = requests.post(f"{API_URL}/chat", json=payload, headers=headers, timeout=60)
                response.raise_for_status() # Lanza excepción si el status no es 200
                
                data = response.json()
                respuesta_ia = data.get("response", "Lo siento, hubo un error procesando la ontología.")
                
                st.markdown(respuesta_ia)
                st.session_state.messages.append({"role": "assistant", "content": respuesta_ia})
                
            # MEJORA DE RESILIENCIA: Captura específica de errores
            except requests.exceptions.HTTPError as http_err:
                if response.status_code in [401, 403]:
                    st.error("Error 401/403 (Unauthorized): La llave maestra del Cliente Humano no coincide o caducó. Sincroniza CHATBOT_MASTER_API_KEY en Railway.")
                else:
                    st.error(f"Error HTTP del Core Server: {http_err}")
            except requests.exceptions.ConnectionError:
                st.error("Error 502/503: No se pudo contactar al API Core. Verifica que el servicio API esté 'Healthy' en Railway.")
            except requests.exceptions.Timeout:
                st.error("Error 504: El agente cognitivo tardó demasiado en responder.")
            except Exception as e:
                st.error(f"Error interno: {str(e)}")
