"""
studio_graph.py
Versión puramente ontológica (desacoplada) del grafo para LangGraph Studio.
Cero dependencias de Odoo, PostgreSQL, Gmail, OpenAI o variables de entorno.
Se enfoca exclusivamente en la topología de nodos y aristas.
"""

from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

# 1. Definición Epistemológica del Estado (Puro Tipado)
class JarviState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    contexto_tecnico: dict

# 2. Definición de Herramientas (Mockup sin lógica de negocio)
@tool
def procesar_oportunidad_backend(nombre: str, telefono: str, email: str, topologia: str) -> str:
    """Inyecta un lead en el flujo de n8n."""
    return "Lead procesado (Simulación)"

# 3. Definición de Nodos (Sin dependencias externas ni de red)
def clasificador_topologia_node(state: JarviState):
    """Nodo simulado para clasificación de topología"""
    return state

def validador_geolocalizacion_node(state: JarviState):
    """Nodo simulado para validación de zona CNEE"""
    return state

def chatbot_node(state: JarviState):
    """Nodo simulado del agente cognitivo"""
    return state

# 4. Construcción Ontológica (Topología estricta)
graph_builder = StateGraph(JarviState)

graph_builder.add_node("clasificador", clasificador_topologia_node)
graph_builder.add_node("validador", validador_geolocalizacion_node)
graph_builder.add_node("chatbot", chatbot_node)
graph_builder.add_node("tools", ToolNode([procesar_oportunidad_backend]))

graph_builder.add_edge(START, "clasificador")
graph_builder.add_edge("clasificador", "validador")
graph_builder.add_edge("validador", "chatbot")
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")

# 5. Compilación aislada en memoria
checkpointer_studio = MemorySaver()
jarvi_graph_studio = graph_builder.compile(checkpointer=checkpointer_studio)
