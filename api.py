"""
api.py - Servidor FastAPI con checkpointing garantizado.
Se usa ainvoke para asegurar persistencia y luego se transmiten los tokens.
Se conservan todos los middlewares, autenticación, telemetría y logs.
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

from schemas import ChatRequest, ChatResponse, AudioRequest, ImageRequest
from agent_graph import create_graph
from config import ISOConfigValidator
from telemetry import (
    trace_id_var, span_id_var, parent_span_id_var,
    generate_trace_span, log_telemetry_event, start_batch_worker
)

# ---------------------------------------------------------------------------
# Esquemas adicionales de validación de datos (Pydantic)
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api")

# ---------------------------------------------------------------------------
# Seguridad – autenticación por API Key (ISO/IEC 27001)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

# ---------------------------------------------------------------------------
# Control de concurrencia
# ---------------------------------------------------------------------------
locks = defaultdict(asyncio.Lock)

# ---------------------------------------------------------------------------
# Taxonomía de errores
# ---------------------------------------------------------------------------
def taxonomy_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"

# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación
# ---------------------------------------------------------------------------
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida – servicio no disponible")

    # Sanitizar URL
    try:
        parsed = urlparse(db_url)
        query = parse_qs(parsed.query)
        for p in ["pool_size", "max_overflow", "pool_timeout"]:
            query.pop(p, None)
        clean_query = urlencode(query, doseq=True)
        db_url_clean = urlunparse(parsed._replace(query=clean_query))
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

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.03",
              lifespan=lifespan, dependencies=[Depends(validar_api_key)])

# ---------------------------------------------------------------------------
# Middleware de telemetría
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
# Endpoint ACK
# ---------------------------------------------------------------------------
@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    return {"status": "ACK received", "trace_id": trace_id}

# ---------------------------------------------------------------------------
# Función de generación de tokens (con checkpointing garantizado)
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    # Inyectar trace_id en el config para que esté disponible en el grafo
    trace_id = trace_id_var.get()
    config = {"configurable": {"thread_id": thread_id}}
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["trace_id"] = trace_id

    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}
    logger.info(f"Ejecutando chat para thread_id={thread_id}, trace_id={trace_id}")

    async with locks[thread_id]:
        # 1. Invocar el grafo (ainvoke garantiza checkpoint)
        resultado = await graph.ainvoke(estado_inicial, config=config)
        messages = resultado.get("messages", [])
        ctx = resultado.get("contexto_tecnico", {})

        logger.info(f"Contexto final para thread {thread_id}: {ctx}")

        # 2. Extraer la última respuesta del asistente
        respuesta_final = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                respuesta_final = msg.content
                break

        # 3. Simular streaming de tokens (dividir en palabras)
        if respuesta_final:
            tokens = respuesta_final.split()
            for i, token in enumerate(tokens):
                # Añadir espacio entre palabras
                sep = " " if i < len(tokens)-1 else ""
                yield f"data: {json.dumps({'token': token + sep})}\n\n"
                await asyncio.sleep(0.03)
        else:
            yield f"data: {json.dumps({'token': '(acción ejecutada)'})}\n\n"

        # Enviar contexto al final
        yield f"data: {json.dumps({'contexto_tecnico': ctx})}\n\n"

# ---------------------------------------------------------------------------
# Endpoint principal /chat
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Endpoints auxiliares (aún no implementados)
# ---------------------------------------------------------------------------
@app.post("/stt")
async def speech_to_text(request: AudioRequest):
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar Whisper")

@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar TTS")

@app.post("/vision/analyze")
async def analizar_factura(request: ImageRequest):
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar visión")

@app.post("/products")
async def consultar_productos(topologia: str = "on-grid"):
    raise HTTPException(status_code=501, detail="No implementado – pendiente exponer catálogo")
