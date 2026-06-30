import os
import secrets
import traceback
import logging
from fastapi import FastAPI, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

# Importaciones del ecosistema homologado de negocio
from agent_graph import create_graph, InferenciaEnergetica
from vision import procesar_imagen_factura
from audit import notificar_error_runtime
import config

# --- 0. Configuración de Logging de Producción ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("aisa_api_core")

app = FastAPI(
    title="Core Cognitivo API - AISA Solar",
    description="API de razonamiento y visión para Jarvi 2.0",
    version="2.0.0"
)

# Configuración CORS para aislar el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En máxima seguridad, restringir a la URL interna de Streamlit
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Inicialización y Control de Persistencia del Grafo ---
CHECKPOINTER_MOTOR = getattr(config, "checkpointer", None) 
jarvi_graph = create_graph(checkpointer=CHECKPOINTER_MOTOR)
logger.info("Motor cognitivo de LangGraph inicializado correctamente.")

# --- 2. Modelos Pydantic (Contratos de Datos Estrictos) ---
class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="Identificador único de la sesión del usuario")
    message: str = Field(..., description="Prompt de texto del cliente humano")

class VisionRequest(BaseModel):
    thread_id: str = Field(..., description="Identificador único de la sesión del usuario")
    image_base64: str = Field(..., description="Cadena Base64 de la imagen de la factura")

# --- 3. Configuración de Seguridad (Bearer Token) ---
security_bearer = HTTPBearer()
API_KEY_SECRET = os.getenv("CHATBOT_MASTER_API_KEY")

def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security_bearer)):
    """Verifica la API Key en tiempo constante para prevenir Timing Attacks."""
    if not API_KEY_SECRET:
        logger.error("FATAL: CHATBOT_MASTER_API_KEY no está definida en las variables de entorno.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de configuración del servidor."
        )
        
    if not secrets.compare_digest(credentials.credentials, API_KEY_SECRET):
        logger.warning(f"Intento de acceso denegado con token inválido.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso Denegado: API Key inválida o ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# --- 4. Endpoints de Negocio ---

@app.get("/health", tags=["Infraestructura"])
async def health_check():
    """Endpoint vital para los healthchecks de Railway."""
    return {"status": "online", "service": "Core Cognitivo AISA Solar"}

@app.post("/chat", dependencies=[Depends(verify_api_key)], tags=["Cognitivo"])
async def chat_endpoint(payload: ChatRequest, background_tasks: BackgroundTasks):
    config_ejecucion = {
        "configurable": {"thread_id": payload.thread_id},
        "tags": ["aisa-produccion-solar"]
    }
    
    try:
        # Invoca el grafo con la estructura de entrada homologada
        response_state = jarvi_graph.invoke(
            {"messages": [HumanMessage(content=payload.message)]}, 
            config=config_ejecucion
        )
        
        ultima_respuesta = response_state["messages"][-1].content
        contexto_actual = response_state.get("contexto_tecnico", {})
        
        return {
            "response": ultima_respuesta,
            "contexto_tecnico": contexto_actual
        }
        
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"Error en chat_endpoint (Thread: {payload.thread_id}): {str(e)}")
        
        session_snapshot = {
            "thread_id": payload.thread_id,
            "fase_actual": "API_SERVER_CHAT_RUNTIME",
            "tags_ejecucion": config_ejecucion["tags"]
        }
        
        # Disparo asíncrono a auditoría ISO
        background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, payload.message)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ha ocurrido un problema técnico inesperado procesando tu solicitud en el core cognitivo."
        )

@app.post("/vision/analyze", dependencies=[Depends(verify_api_key)], tags=["Multimodal"])
async def vision_endpoint(payload: VisionRequest, background_tasks: BackgroundTasks):
    try:
        # Extrae datos estructurados de la factura
        datos_extraidos = procesar_imagen_factura(payload.image_base64)
        
        # Inyecta resultados directamente en el estado persistente de LangGraph
        config_ejecucion = {"configurable": {"thread_id": payload.thread_id}}
        
        jarvi_graph.update_state(
            config_ejecucion,
            {
                "contexto_tecnico": {
                    "empresa_electrica": datos_extraidos.get("empresa_electrica"),
                    "requiere_auditoria_electrica": True
                }
            },
            as_node="clasificador" # Fuerza el asentamiento en el nodo inicial
        )
        
        return {
            "status": "ok",
            "extracted_data": datos_extraidos
        }
        
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"Error en vision_endpoint (Thread: {payload.thread_id}): {str(e)}")
        
        session_snapshot = {"thread_id": payload.thread_id, "fase_actual": "API_SERVER_VISION_MULTIMODAL"}
        background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, "Carga de archivo binario/Base64 Factura Eléctrica")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar el pipeline de visión artificial de la factura."
        )
