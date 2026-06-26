from fastapi import FastAPI, Request
from agent_graph import inicializar_motor_jarvi
from langchain_core.messages import HumanMessage
import config

app = FastAPI()
jarvi_graph = inicializar_motor_jarvi()

@app.post("/chat")
async def chat_endpoint(request: Request):
    data = await request.json()
    thread_id = data.get("thread_id")
    prompt = data.get("message")
    
    # Mantenemos exactamente tu lógica de configuración de ejecución
    config_ejecucion = {
        "configurable": {"thread_id": thread_id},
        "tags": ["aisa-produccion-solar"]
    }
    
    response_state = jarvi_graph.invoke(
        {"messages": [HumanMessage(content=prompt)]}, 
        config=config_ejecucion
    )
    
    # Extraemos solo la última respuesta del agente
    ultima_respuesta = response_state["messages"][-1].content
    return {"response": ultima_respuesta}
