import os
import secrets
import traceback
from fastapi import FastAPI, Request, Depends, HTTPException, Security, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from langchain_core.messages import HumanMessage

# Importaciones de tu ecosistema homologado de negocio
from agent_graph import create_graph, InferenciaEnergetica
from vision import procesar_imagen_factura
from audit import notificar_error_runtime
import config

app = FastAPI(title="Core Cognitivo API - AISA Solar")

# --- 1. Inicialización y Control de Persistencia del Grafo ---
# Nota: Aquí se asume que config.py inicializa tu Pool/Saver de PostgreSQL (ej. AsyncPostgresSaver o MemorySaver de respaldo)
CHECKPOINTER_MOTOR = getattr(config, "checkpointer", None) 
jarvi_graph = create_graph(checkpointer=CHECKPOINTER_MOTOR)

# --- 2. Configuración de Seguridad Intacta (Bearer Token) ---
security_bearer = HTTPBearer()
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

# --- 3. Endpoint de Chat Protegido e Integrado con Auditoría ---
@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def chat_endpoint(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    thread_id = data.get("thread_id")
    prompt = data.get("message")
    
    if not thread_id or not prompt:
        raise HTTPException(status_code=400, detail="Faltan parámetros requeridos: thread_id o message.")
    
    config_ejecucion = {
        "configurable": {"thread_id": thread_id},
        "tags": ["aisa-produccion-solar"]
    }
    
    try:
        # Invoca el grafo con la estructura de entrada homologada
        response_state = jarvi_graph.invoke(
            {"messages": [HumanMessage(content=prompt)]}, 
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
        
        # Snapshot técnico de la sesión para empaquetar en la auditoría ISO
        session_snapshot = {
            "thread_id": thread_id,
            "fase_actual": "API_SERVER_CHAT_RUNTIME",
            "tags_ejecucion": config_ejecucion["tags"]
        }
        
        # Disparo asíncrono en segundo plano a tu audit.py sin bloquear al cliente de la App
        background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, prompt)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ha ocurrido un problema técnico inesperado procesando tu solicitud en el core cognitivo."
        )

# --- 4. Nuevo Endpoint de Visión Multimodal Integrado (Fase 3) ---
@app.post("/vision/analyze", dependencies=[Depends(verify_api_key)])
async def vision_endpoint(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    thread_id = data.get("thread_id")
    image_base64 = data.get("image_base64")
    
    if not thread_id or not image_base64:
        raise HTTPException(status_code=400, detail="Faltan parámetros requeridos: thread_id o image_base64.")
        
    try:
        # Extrae datos estructurados de la factura (EEGSA/ENERGUATE, consumo_kwh, monto) desde vision.py
        datos_extraidos = procesar_imagen_factura(image_base64)
        
        # Inyecta los resultados del análisis directo en el estado persistente del Grafo de LangGraph
        config_ejecucion = {"configurable": {"thread_id": thread_id}}
        
        # Actualizamos el estado de manera externa para que Jarvi conozca los datos de consumo en el siguiente prompt
        jarvi_graph.update_state(
            config_ejecucion,
            {
                "contexto_tecnico": {
                    "empresa_electrica": datos_extraidos.get("empresa_electrica"),
                    "requiere_auditoria_electrica": True
                }
            },
            as_node="clasificador" # Forzamos que se asiente sobre el nodo clasificador inicial
        )
        
        return {
            "status": "ok",
            "extracted_data": datos_extraidos
        }
        
    except Exception as e:
        tb_str = traceback.format_exc()
        session_snapshot = {"thread_id": thread_id, "fase_actual": "API_SERVER_VISION_MULTIMODAL"}
        background_tasks.add_task(notificar_error_runtime, e, tb_str, session_snapshot, "Carga de archivo binario/Base64 Factura Eléctrica")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar el pipeline de visión artificial de la factura."
        )
