"""
api_server.py (backend central JARVI 2.0.03 + CTFOM)
=====================================================
Servidor FastAPI que centraliza toda la lógica de negocio,
telemetría cognitiva y trazabilidad.
Versión mejorada con manejo robusto de streaming y CORS.
"""

import os
import asyncio
import json
import time
import logging
from collections import defaultdict
from typing import AsyncGenerator, Optional

import psutil
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage

from schemas import ChatRequest, ChatResponse
from agent_graph import create_graph
from telemetry import (
    trace_id_var, span_id_var, parent_span_id_var,
    generate_trace_span, log_telemetry_event, _batch_worker
)

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api")

# ---------------------------------------------------------------------------
# Seguridad – API Key
# ---------------------------------------------------------------------------
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    if not auth or auth != f"Bearer {API_KEY}":
        logger.warning("Intento de acceso no autorizado")
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

# ---------------------------------------------------------------------------
# Control de concurrencia
# ---------------------------------------------------------------------------
locks = defaultdict(asyncio.Lock)

# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
async def persistir_evento_auditoria(thread_id: str, run_id: str, payload: dict):
    try:
        logger.info("AUDIT|%s|%s|%s", thread_id, run_id, json.dumps(payload, default=str))
    except Exception as e:
        logger.error("Error en auditoría: %s", e)

def taxonomy_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"

# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida")
    checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
    graph = create_graph(checkpointer)
    logger.info("JARVI 2.0.03 API inicializada – Grafo listo")
    # Arrancar worker CTFOM
    asyncio.create_task(_batch_worker())
    logger.info("CTFOM worker iniciado")
    yield
    logger.info("Apagando API JARVI")

app = FastAPI(
    title="JARVI 2.0.03 API Central",
    version="2.0.03",
    lifespan=lifespan,
    dependencies=[Depends(validar_api_key)]
)

# ---------------------------------------------------------------------------
# Middleware CTFOM
# ---------------------------------------------------------------------------
@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    generate_trace_span()
    start = time.perf_counter()
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().used / (1024 * 1024)
    try:
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        await log_telemetry_event(
            trace_id_var.get(), span_id_var.get(), "",
            layer="api", event_type="END", latency_ms=elapsed,
            cpu_percent=cpu, memory_mb=mem,
            metadata={"path": request.url.path, "method": request.method}
        )
        return response
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        await log_telemetry_event(
            trace_id_var.get(), span_id_var.get(), "",
            layer="api", event_type="ERROR", latency_ms=elapsed,
            cpu_percent=cpu, memory_mb=mem,
            error_code=taxonomy_error(e),
            metadata={"path": request.url.path}
        )
        raise

# ---------------------------------------------------------------------------
# Endpoint ACK (telemetría)
# ---------------------------------------------------------------------------
@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    return {"status": "ACK received", "trace_id": trace_id}

# ---------------------------------------------------------------------------
# Generación de tokens SSE
# ---------------------------------------------------------------------------
async def generar_sse(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    config = {"configurable": {"thread_id": thread_id}}
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}

    async with locks[thread_id]:
        evento_llm = False
        async for evento in graph.astream_events(estado_inicial, config=config, version="v2"):
            kind = evento["event"]
            if kind == "on_chat_model_stream":
                contenido = evento["data"]["chunk"].content
                if contenido:
                    # Escapamos saltos de línea para mantener el formato SSE
                    contenido_escapado = contenido.replace('\n', '\\n')
                    yield f"data: {{\"token\": \"{contenido_escapado}\"}}\n\n"
                    evento_llm = True
            elif kind == "on_chain_end" and evento["name"] == "LangGraph":
                estado_final = evento["data"]["output"]
                ctx = estado_final.get("contexto_tecnico", {})
                yield f"data: {{\"contexto_tecnico\": {json.dumps(ctx)}}}\n\n"
                break

        if not evento_llm:
            yield f"data: {{\"token\": \"(acción ejecutada)\"}}\n\n"

# ---------------------------------------------------------------------------
# Endpoint /chat (streaming SSE)
# ---------------------------------------------------------------------------
@app.post("/chat")
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        return StreamingResponse(
            generar_sse(request.thread_id, request.message),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Authorization, Content-Type"
            }
        )
    except Exception as e:
        logger.error("Error en /chat: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del agente")

# ---------------------------------------------------------------------------
# Resto de endpoints (stt, tts, visión, productos) - sin cambios
# ---------------------------------------------------------------------------
@app.post("/stt")
async def speech_to_text():
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/tts")
async def text_to_speech():
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/vision/analyze")
async def analizar_factura():
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/products")
async def consultar_productos(topologia: str = "on-grid"):
    raise HTTPException(status_code=501, detail="No implementado")
