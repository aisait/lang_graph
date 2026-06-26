import os
import asyncio
from collections import defaultdict
from fastapi import FastAPI, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from schemas import ChatRequest, ChatResponse
from agent_graph import create_graph

# --- Estructura de Control de Concurrencia ---
locks = defaultdict(asyncio.Lock)

# --- Función de Auditoría Forense (Desacoplada) ---
async def persistir_evento_auditoria(thread_id: str, run_id: str, payload: dict):
    """
    Registra eventos en la base de datos sin bloquear el hilo principal.
    Preserva la integridad de la auditoría 360°.
    """
    try:
        # Aquí va la lógica de inserción en audit_events (Previa auditoría)
        pass 
    except Exception as e:
        print(f"Error crítico en auditoría asíncrona: {e}")

# --- Gestión del Ciclo de Vida ---
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    # Inicialización centralizada y segura del Checkpointer en Postgres
    checkpointer = AsyncPostgresSaver.from_conn_string(os.getenv("DATABASE_URL"))
    await checkpointer.setup()
    graph = await create_graph(checkpointer)
    yield
    # Cleanup si fuera necesario

app = FastAPI(lifespan=lifespan)

# --- Endpoint de Producción ---
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        # Válvula de Seguridad: Serialización por thread_id
        async with locks[request.thread_id]:
            config = {"configurable": {"thread_id": request.thread_id}}
            
            # Ejecución atómica del grafo
            result = await graph.ainvoke({"input": request.message}, config=config)
            
            # Disparo de Auditoría 360° (Fire-and-Forget controlado)
            run_id = result.get("run_id", "manual_exec")
            background_tasks.add_task(
                persistir_evento_auditoria, 
                request.thread_id, 
                run_id, 
                request.dict()
            )
            
            return ChatResponse(
                response=result["output"],
                run_id=run_id
            )
            
    except Exception as e:
        # Mantenemos el manejo de excepciones para transparencia operativa
        raise HTTPException(status_code=500, detail=str(e))
