import streamlit as st
import requests
import os

# Mantenemos el estado de Streamlit - Redirigido de forma segura a la API Central
if "api_url" not in st.session_state:
    st.session_state.api_url = os.getenv("API_URL", "http://localhost:8000")

# Para Streamlit, seguimos usando memoria volátil o la misma BD delegada a través de la API REST
# Esto elimina las importaciones directas de agent_graph y previene deadlocks concurrentes.
def enviar_mensaje_api(message: str, thread_id: str) -> dict:
    payload = {"thread_id": thread_id, "message": message}
    response = requests.post(f"{st.session_state.api_url}/chat", json=payload, timeout=30)
    if response.status_code == 200:
        return response.json()
    raise Exception(f"Fallo en la comunicación con el Core: {response.text}")

# Ahora usas st.session_state para orquestar la llamada asíncrona hacia tus nodos a través de FastAPI
