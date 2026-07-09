"""
api.py - Servidor FastAPI con checkpointing garantizado.
Se usa ainvoke para asegurar persistencia y luego se transmiten los tokens.
Se conservan todos los middlewares, autenticación, telemetría y logs.
Ahora con unificación de threads por WhatsApp.
"""

import os
import asyncio
import json
import time
import logging
import re
from collections import defaultdict
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psutil
import asyncpg
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage

from schemas import ChatRequest, ChatResponse, AudioRequest, ImageRequest
from agent_graph import create_graph, normalizar_contacto
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

# =============================================================================
# NUEVA FUNCIÓN: Extraer WhatsApp del mensaje (regex simple)
# =============================================================================
def extraer_whatsapp(mensaje: str) -> str | None:
    """
    Extrae el primer número de WhatsApp (con o sin código de país) del mensaje.
    """
    if not mensaje:
        return None
    # Buscar patrones de teléfono: +502 1234-5678, 50212345678, 12345678, etc.
    match = re.search(r'(\+?[0-9]{1,3}[-.\s]?)?[0-9]{4,10}', mensaje)
    if match:
        # Normalizar: eliminar espacios, guiones, etc.
        numero = re.sub(r'[\s\-\.]', '', match.group(0))
        # Si tiene código de país, asegurar formato +502
        if numero.startswith('+'):
            return numero
        elif len(numero) == 8:
            return f"+502 {numero[:4]}-{numero[4:]}"
        elif len(numero) == 11 and numero.startswith('502'):
            return f"+{numero[:3]} {numero[3:7]}-{numero[7:]}"
        else:
            return f"+502 {numero}"  # Asumir Guatemala
    return None

# =============================================================================
# NUEVA FUNCIÓN: Obtener thread_id existente para un WhatsApp
# =============================================================================
async def obtener_thread_por_whatsapp(whatsapp: str) -> str | None:
    """
    Consulta la base de datos para encontrar un thread_id asociado al WhatsApp.
    """
    conn = None
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        row = await conn.fetchrow(
            "SELECT thread_id FROM threads WHERE whatsapp_id = $1",
            whatsapp
        )
        if row:
            return row["thread_id"]
        return None
    except Exception as e:
        logger.warning(f"Error al consultar thread por whatsapp: {e}")
        return None
    finally:
        if conn:
            await conn.close()

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
# Función de generación de tokens (con checkpointing garantizado y sin delays)
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str, run_name: str | None = None) -> AsyncGenerator[str, None]:
    # Inyectar trace_id en el config
    trace_id = trace_id_var.get()
    config = {"configurable": {"thread_id": thread_id}}
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["trace_id"] = trace_id

    # Si se proporcionó un run_name (WhatsApp normalizado), usarlo
    if run_name and run_name != "Pendiente":
        config["run_name"] = run_name
        config["metadata"]["whatsapp"] = run_name
        logger.info(f"run_name establecido a: {run_name} para thread {thread_id}")
    else:
        # Si no, intentar obtener de la BD (por si ya estaba registrado)
        try:
            conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
            row = await conn.fetchrow(
                "SELECT whatsapp_id FROM threads WHERE thread_id = $1",
                thread_id
            )
            if row and row["whatsapp_id"]:
                config["run_name"] = row["whatsapp_id"]
                config["metadata"]["whatsapp"] = row["whatsapp_id"]
                logger.info(f"run_name recuperado de BD: {row['whatsapp_id']}")
            await conn.close()
        except Exception as e:
            logger.warning(f"No se pudo obtener whatsapp para run_name: {e}")

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

        # 3. Simular streaming de tokens (sin sleeps, rápido)
        if respuesta_final:
            tokens = respuesta_final.split()
            for i, token in enumerate(tokens):
                sep = " " if i < len(tokens)-1 else ""
                yield f"data: {json.dumps({'token': token + sep})}\n\n"
        else:
            yield f"data: {json.dumps({'token': 'No se pudo generar una respuesta. Por favor, intenta de nuevo.'})}\n\n"

        # Enviar contexto al final
        yield f"data: {json.dumps({'contexto_tecnico': ctx})}\n\n"

# ---------------------------------------------------------------------------
# Endpoint principal /chat (con unificación de threads)
# ---------------------------------------------------------------------------
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # 1. Extraer WhatsApp del mensaje
    whatsapp_raw = extraer_whatsapp(request.message)
    thread_id_final = request.thread_id
    run_name = "Pendiente"

    # 2. Si se encontró un WhatsApp, buscar thread existente en BD
    if whatsapp_raw:
        # Normalizar el WhatsApp (usar función auxiliar si existe, o simple)
        # Para simplificar, usamos el extraído y lo normalizamos con la función del agente (importada)
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            run_name = whatsapp_norm
            # Buscar thread_id existente
            existing_thread = await obtener_thread_por_whatsapp(whatsapp_norm)
            if existing_thread:
                thread_id_final = existing_thread
                logger.info(f"Thread unificado: usando thread_id {thread_id_final} para WhatsApp {whatsapp_norm}")
            else:
                # No existe, se creará nuevo con el thread_id del request
                logger.info(f"Nuevo thread para WhatsApp {whatsapp_norm}")

    # 3. Llamar a generar_tokens con el thread_id final y el run_name
    return StreamingResponse(
        generar_tokens(thread_id_final, request.message, run_name),
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
