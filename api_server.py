import os
import json
import secrets
import traceback
import logging
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langserve import add_routes 

# Lógica de negocio intacta
from agent_graph import create_graph, InferenciaEnergetica
from vision import procesar_imagen_factura
from audit import notificar_error_runtime
import config

# Logging de Producción
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("aisa_api_core")

app = FastAPI(
    title="Core Cognitivo API - AISA Solar",
    description="API de razonamiento y visión agéntica",
    version="2.0.0"
)

# CORS Permisivo para LangSmith Studio
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Inicialización Singleton del Grafo
CHECKPOINTER_MOTOR = getattr(config, "checkpointer", None) 
jarvi_graph = create_graph(checkpointer=CHECKPOINTER_MOTOR)
logger.info("Motor cognitivo de LangGraph inicializado y montado en memoria RAM.")

class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="Identificador único de la sesión")
    message: str = Field(..., description="Prompt de entrada")

class VisionRequest(BaseModel):
    thread_id: str = Field(..., description="Identificador único de la sesión")
    image_base64: str = Field(..., description="Cadena Base64 de la factura")

security_bearer = HTTPBearer()
API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY", "aisa_fallback_secret_123")

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security_bearer)):
    if not secrets.compare_digest(credentials.credentials, API_KEY_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso Denegado: API Key inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

@app.get("/health", tags=["Infraestructura"])
async def health_check():
    return {"status": "online", "service": "AISA Solar API"}

@app.post("/chat", dependencies=[Depends(verify_api_key)], tags=["Cognitivo"])
async def chat_endpoint(payload: ChatRequest, background_tasks: BackgroundTasks):
    config_ejecucion = {
        "configurable": {"thread_id": payload.thread_id},
        "tags": ["aisa-produccion-solar"]
    }
    
    async def event_generator():
        try:
            async for event in jarvi_graph.astream_events(
                {"messages": [HumanMessage(content=payload.message)]}, 
                config=config_ejecucion,
                version="v2"
            ):
                event_type = event.get("event", "")
                if "stream" in event_type or event_type in ["on_chat_model_stream", "on_llm_stream"]:
                    data_chunk = event.get("data", {})
                    chunk_obj = data_chunk.get("chunk")
                    if chunk_obj and hasattr(chunk_obj, "content"):
                        token = chunk_obj.content
                        if token:
                            yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            
            state_snapshot = jarvi_graph.get_state(config_ejecucion)
            contexto_actual = state_snapshot.values.get("contexto_tecnico", {}) if state_snapshot else {}
            yield f"data: {json.dumps({'contexto_tecnico': contexto_actual}, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"Error de ejecución: {str(e)}")
            session_snapshot = {"thread_id": payload.thread_id, "fase": "API_CHAT_RUNTIME"}
            background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, payload.message)
            yield f"data: {json.dumps({'error': 'Interrupción técnica procesada.'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/vision/analyze", dependencies=[Depends(verify_api_key)], tags=["Multimodal"])
async def vision_endpoint(payload: VisionRequest, background_tasks: BackgroundTasks):
    try:
        datos_extraidos = procesar_imagen_factura(payload.image_base64)
        config_ejecucion = {"configurable": {"thread_id": payload.thread_id}}
        
        jarvi_graph.update_state(
            config_ejecucion,
            {"contexto_tecnico": {"empresa_electrica": datos_extraidos.get("empresa_electrica"), "requiere_auditoria_electrica": True}},
            as_node="clasificador"
        )
        return {"status": "ok", "extracted_data": datos_extraidos}
        
    except Exception as e:
        tb_str = traceback.format_exc()
        session_snapshot = {"thread_id": payload.thread_id}
        background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, "Visión Artificial")
        raise HTTPException(status_code=500, detail="Fallo en módulo multimodal.")

add_routes(app, jarvi_graph, path="/jarvi")
