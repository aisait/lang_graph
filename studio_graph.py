"""
studio_graph.py
Exporta el grafo completo de JARVI 2.0 con MemorySaver para LangGraph Studio.
Garantiza que el comportamiento en Studio sea idéntico al de producción.
Estándares: ISO/IEC 25010, ISO/IEC 29119.

Este archivo es el punto de entrada para el Agent Server que ejecuta `langgraph dev`.
El grafo se compila con un checkpointer en memoria (MemorySaver) para evitar
dependencias externas (PostgreSQL) durante la depuración visual.Exporta el grafo completo de JARVI 2.0 con MemorySaver para LangGraph Studio.
Garantiza que el comportamiento en Studio sea idéntico al de producción.
Estándares: ISO/IEC 25010, ISO/IEC 29119.
"""

from agent_graph import create_graph
from langgraph.checkpoint.memory import MemorySaver

checkpointer_studio = MemorySaver()
jarvi_graph_studio = create_graph(checkpointer_studio)

# Alias para compatibilidad con langgraph.json
jarvi_graph = jarvi_graph_studio
