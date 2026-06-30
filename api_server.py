import os
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from agent_graph import inicializar_motor_jarvi
from langchain_core.messages import HumanMessage
import config

app = FastAPI(title="Core Cognitivo API")

# 1. Inicialización del Grafo
jarvi_graph = inicializar_motor_jarvi()

# 2. Configuración de Seguridad (Bearer Token)
security_bearer = HTTPBearer()
# Railway inyectará esta variable de entorno que configuraremos en el siguiente paso
API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security_bearer)):
    """
    Verifica la API Key en tiempo constante para prevenir Timing Attacks.
    """
    if not secrets.compare_digest(credentials.credentials, API_KEY_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso Denegado: API Key inválida o ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# 3. Endpoint Protegido
@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def chat_endpoint(request: Request):
    data = await request.json()
    thread_id = data.get("thread_id")
    prompt = data.get("message")
    
    config_ejecucion = {
        "configurable": {"thread_id": thread_id},
        "tags": ["aisa-produccion-solar"]
    }
    
    response_state = jarvi_graph.invoke(
        {"messages": [HumanMessage(content=prompt)]}, 
        config=config_ejecucion
    )
    
    ultima_respuesta = response_state["messages"][-1].content
    return {"response": ultima_respuesta}
