from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from schemas import ChatRequest, ChatResponse
from agent_graph import create_graph

# Gestión del ciclo de vida
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    # Inicialización centralizada y segura
    checkpointer = AsyncPostgresSaver.from_conn_string(os.getenv("DATABASE_URL"))
    await checkpointer.setup()
    graph = await create_graph(checkpointer)
    yield
    # Cleanup si fuera necesario

app = FastAPI(lifespan=lifespan)

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        config = {"configurable": {"thread_id": request.thread_id}}
        # Ejecución del grafo
        result = await graph.ainvoke({"input": request.message}, config=config)
        
        return ChatResponse(
            response=result["output"],
            run_id=result.get("run_id", "manual_exec")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
