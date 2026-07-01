# --- streamlit_app.py ---
import streamlit as st
import requests

# --- Consumo API-First (Evita FileNotFound y colapso de memoria) ---
@st.cache_data(ttl=3600)
def fetch_catalogo_remoto():
    try:
        response = requests.get(f"{BACKEND_URL}/api/catalogo", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception:
        # Aquí se mantiene tu resiliencia original
        return {}

def main_loop():
    # El catálogo ahora es un recurso servido por tu propia arquitectura
    catalogo = fetch_catalogo_remoto()
    
    # ... (Tu UI original se mantiene intacta)
    st.sidebar.title("Catálogo Técnico AISA")
    for key, item in catalogo.items():
        if st.sidebar.button(item['nombre']):
            st.write(f"Accediendo a: {item['url']}")
