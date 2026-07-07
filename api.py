"""
api.py - Servidor FastAPI con checkpointing nativo.
"""

import os
import asyncio
import json
import time
import logging
from collections import defaultdict
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psutil
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage

from schemas import ChatRequest
from agent_graph import create_graph
from telemetry import (
    generate_trace_span, log_telemetry_event, start_batch_worker,
    trace_id_var, span_id_var
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api")

API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

locks = defaultdict(asyncio.Lock)

def taxonomy_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"

graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida")
    try:
        parsed_url = urlparse(db_url)
        query_params = parse_qs(parsed_url.query)
        for param in ["pool_size", "max_overflow", "pool_timeout"]:
            query_params.pop(param, None)
        clean_query = urlencode(query_params, doseq=True)
        db_url_clean = urlunparse(parsed_url._replace(query=clean_query))
    except Exception:
        db_url_clean = db_url

    async with AsyncExitStack() as stack:
        logger.info("Inicializando Pool de conexiones...")
        raw_checkpointer = AsyncPostgresSaver.from_conn_string(db_url_clean)
        checkpointer = await stack.enter_async_context(raw_checkpointer)
        await checkpointer.setup()
        graph = create_graph(checkpointer)
        logger.info("JARVI 2.0 API inicializada – Grafo listo")
        start_batch_worker()
        logger.info("CTFOM: worker de telemetría iniciado")
        yield
    logger.info("Apagando API JARVI")

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.03", lifespan=lifespan,
              dependencies=[Depends(validar_api_key)])

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
# Endpoint principal con checkpointing garantizado
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    """
    Usa ainvoke para garantizar que el checkpoint se guarde.
    Luego transmite los tokens del último mensaje (AIMessage).
    """
    config = {"configurable": {"thread_id": thread_id}}
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}

    logger.info(f"Ejecutando chat para thread_id={thread_id}")

    async with locks[thread_id]:
        # Invocamos el grafo de forma síncrona (ainvoke) para asegurar checkpoint
        resultado = await graph.ainvoke(estado_inicial, config=config)
        # El resultado contiene el estado final con 'messages' y 'contexto_tecnico'
        messages = resultado.get("messages", [])
        ctx = resultado.get("contexto_tecnico", {})
        logger.info(f"Contexto final para thread {thread_id}: {ctx}")

        # Extraer la última respuesta del asistente
        respuesta_final = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                respuesta_final = msg.content
                break

        # Simular streaming token por token (dividir por palabras o caracteres)
        # Para una experiencia real, se puede usar el modelo de streaming, pero aquí
        # se emula con división de palabras para que el frontend reciba tokens.
        if respuesta_final:
            # Dividir en tokens (simplificado)
            tokens = respuesta_final.split()
            for token in tokens:
                # Enviar cada token como evento SSE
                yield f"data: {json.dumps({'token': token + ' '})}\n\n"
                await asyncio.sleep(0.05)  # pequeño delay para simular streaming
        else:
            yield f"data: {json.dumps({'token': '(acción ejecutada)'})}\n\n"

        # Enviar contexto al final
        yield f"data: {json.dumps({'contexto_tecnico': ctx})}\n\n"

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        generar_tokens(request.thread_id, request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )

# Endpoints adicionales (stt, tts, vision, products) se mantienen igual (no implementados)
