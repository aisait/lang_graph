"""
studio_graph.py
Exporta el grafo completo de JARVI 2.0 con MemorySaver para LangGraph Studio.
Garantiza que el comportamiento en Studio sea idéntico al de producción.
Estándares: ISO/IEC 25010, ISO/IEC 29119.

Este archivo es el punto de entrada para el Agent Server que ejecuta `langgraph dev`.
El grafo se compila con un checkpointer en memoria (MemorySaver) para evitar
dependencias externas (PostgreSQL) durante la depuración visual.
"""

import logging
from agent_graph import create_graph
from langgraph.checkpoint.memory import MemorySaver

# Configurar logging para trazabilidad
logger = logging.getLogger(__name__)

try:
    # Crear checkpointer en memoria (no persistente, ideal para Studio)
    checkpointer_studio = MemorySaver()

    # Compilar el grafo con el checkpointer en memoria
    jarvi_graph_studio = create_graph(checkpointer_studio)

    # Alias para compatibilidad con langgraph.json
    jarvi_graph = jarvi_graph_studio

    logger.info("✅ Grafo de JARVI 2.0 cargado correctamente para Studio")

except Exception as e:
    logger.error(f"❌ Error al cargar el grafo para Studio: {e}")
    # Relanzar la excepción para que el servidor lo detecte y falle claramente
    raise
