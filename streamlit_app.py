import streamlit as st
from agent_graph import create_graph
from langgraph.checkpoint.memory import MemorySaver

# Mantenemos el estado de Streamlit
if "graph" not in st.session_state:
    # Para Streamlit, seguimos usando memoria volátil o la misma BD
    memory = MemorySaver() 
    st.session_state.graph = create_graph(memory)

# Ahora usas st.session_state.graph para invocar tus nodos
