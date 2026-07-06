from langgraph.checkpoint.memory import MemorySaver
from agent_graph import create_graph

# Instancia en memoria exclusiva para visualización de gerencia
graph = create_graph(MemorySaver())
