"""
frontend.py - Interfaz mínima de prueba para JARVI 2.0.
Cumple con ISO/IEC 25010 (usabilidad) y 29119 (pruebas).
"""

import streamlit as st
import requests
import os
import json
import uuid

BACKEND_URL = os.getenv("BACKEND_URL", "https://jarvi-backend-production.up.railway.app").rstrip('/')
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY")

if not API_KEY:
    st.error("❌ CHATBOT_MASTER_API_KEY no definida.")
    st.stop()

# Mantener thread_id en URL (persistencia)
if "thread_id" not in st.session_state:
    tid = st.query_params.get("thread_id")
    if tid:
        st.session_state.thread_id = tid
    else:
        st.session_state.thread_id = str(uuid.uuid4())
        st.query_params["thread_id"] = st.session_state.thread_id

st.title("Jarvi - Prueba Mínima")
st.write(f"Thread ID: {st.session_state.thread_id}")

# Historial simple
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Escribe tu mensaje...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""

        try:
            response = requests.post(
                f"{BACKEND_URL}/chat",
                json={"thread_id": st.session_state.thread_id, "message": prompt},
                headers={"Authorization": f"Bearer {API_KEY}"},
                stream=True,
                timeout=120
            )

            if response.status_code != 200:
                st.error(f"Error {response.status_code}: {response.text}")
                st.stop()

            # Leer el stream y acumular tokens
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                json_str = line[6:]
                try:
                    data = json.loads(json_str)
                except:
                    continue
                if "token" in data:
                    full_response += data["token"]
                    placeholder.write(full_response + "▌")
                elif "contexto_tecnico" in data:
                    placeholder.write(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                    with st.expander("Contexto técnico"):
                        st.json(data["contexto_tecnico"])
                    break
            else:
                # Si no hubo evento de contexto, igual guardamos lo que se haya acumulado
                if full_response:
                    st.session_state.messages.append({"role": "assistant", "content": full_response})

        except Exception as e:
            st.error(f"Excepción: {e}")
            st.stop()

    st.rerun()
