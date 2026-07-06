# studio_entry.py
# ARCHIVO EXCLUSIVO PARA DESARROLLO Y VISUALIZACIÓN EN STUDIO LANGRAPH- NO SE USA EN PRODUCCIÓN

from langgraph.checkpoint.memory import MemorySaver
from agent_graph import create_graph

# LangGraph Studio necesita una instancia compilada o una función sin argumentos obligatorios.
# Usamos MemorySaver para renderizar la topología sin conectarnos a la base de datos real.
checkpointer_studio = MemorySaver()

# Exponemos el grafo compilado listo para que Studio lo lea
graph = create_graph(checkpointer_studio)
