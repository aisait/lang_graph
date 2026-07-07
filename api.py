"""
api.py
Servidor central de lógica de negocio de JARVI 2.0 (FastAPI).
Contiene el ciclo de vida del grafo, control de concurrencia, seguridad
y endpoints unificados para todos los canales (Streamlit, n8n, LangSmith).
Incorpora el módulo CTFOM de telemetría cognitiva para trazabilidad
end‑to‑end, detección de cuellos de botella y verificación de despacho.
Estándares: ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
Pruebas de caja negra: BC-T01 a BC-T10 (ver anexo).
"""

import os
import asyncio
import json
import time
import logging
from collections import defaultdict
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psutil  # telemetría de recursos
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage

from schemas import ChatRequest, ChatResponse, AudioRequest, ImageRequest
from agent_graph import create_graph
from config import ISOConfigValidator  # noqa: F401 – asegura entorno válido

# --- CTFOM: módulo de telemetría cognitiva ---
from telemetry import (
    trace_id_var, span_id_var, parent_span_id_var,
    generate_trace_span, log_telemetry_event, start_batch_worker
)

# ---------------------------------------------------------------------------
# Esquemas adicionales de validación de datos (Pydantic)
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    """
    Esquema de validación para las peticiones de síntesis de voz (Text-to-Speech).
    """
    text: str
    voice: str | None = None


# ---------------------------------------------------------------------------
# Configuración de logging (ISO/IEC 26514 – documentación de eventos)
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api")

# ---------------------------------------------------------------------------
# Seguridad – autenticación por API Key (ISO/IEC 27001)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    """
    Valida que la cabecera 'Authorization' contenga el token correcto.
    Prueba de caja negra: BC-T04 (Integración n8n) y BC-T05 (Validación schema).
    """
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

# ---------------------------------------------------------------------------
# Control de concurrencia por sesión (evita escrituras simultáneas)
# ---------------------------------------------------------------------------
locks = defaultdict(asyncio.Lock)

# ---------------------------------------------------------------------------
# Taxonomía de errores alineada con ISO 27001 / 42001
# ---------------------------------------------------------------------------
def taxonomy_error(exc: Exception) -> str:
    """Mapea excepciones a códigos de error estructurados."""
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"


# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación (inicialización del grafo, base de datos y telemetría)
# ---------------------------------------------------------------------------
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicializa el checkpointer de PostgreSQL, compila el grafo una sola vez
    y arranca el worker de inserción batch de telemetría CTFOM.
    Alineado a la especificación de administradores de contexto asíncronos de LangGraph.
    """
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida – servicio no disponible")
    
    # --- SANITIZACIÓN DE LA URL (Evita el error de psycopg con pool_size) ---
    try:
        parsed_url = urlparse(db_url)
        query_params = parse_qs(parsed_url.query)
        parametros_conflictivos = ["pool_size", "max_overflow", "pool_timeout"]
        for param in parametros_conflictivos:
            query_params.pop(param, None)
        clean_query = urlencode(query_params, doseq=True)
        db_url_clean = urlunparse(parsed_url._replace(query=clean_query))
    except Exception as e:
        logger.error("Error al sanitizar DATABASE_URL, se recurrirá al string original: %s", e)
        db_url_clean = db_url
    # ------------------------------------------------------------------------
    
    async with AsyncExitStack() as stack:
        logger.info("Inicializando Pool de conexiones de Postgres para LangGraph Checkpointer...")
        
        raw_checkpointer = AsyncPostgresSaver.from_conn_string(db_url_clean)
        checkpointer = await stack.enter_async_context(raw_checkpointer)
        await checkpointer.setup()
        
        graph = create_graph(checkpointer)
        logger.info("JARVI 2.0 API inicializada – Grafo listo con Checkpointer de PostgreSQL Activo")

        start_batch_worker()
        logger.info("CTFOM: worker de telemetría iniciado")

        yield
        
    logger.info("Apagando API JARVI y liberando recursos del Pool de Base de Datos")


# ---------------------------------------------------------------------------
# Instancia de FastAPI con ciclo de vida y dependencia de seguridad global
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JARVI 2.0 API Central",
    version="2.0.03",
    lifespan=lifespan,
    dependencies=[Depends(validar_api_key)]
)


# ---------------------------------------------------------------------------
# Middleware HTTP para telemetría CTFOM (catch-on-the-middle)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    """
    Captura cada request HTTP: genera trace/span, mide latencia, CPU y memoria,
    y registra un evento de telemetría al finalizar.
    Prueba de caja negra: BC-T07 (Telemetría activa) y BC-T08 (Traza completa).
    """
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
# Endpoint de confirmación de despacho (ACK) para canales externos
# BC-T09 (Despacho verificado)
# ---------------------------------------------------------------------------
@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    """
    Recibe confirmación de entrega desde canales externos (n8n).
    Actualiza dispatch_events en una implementación completa.
    """
    # Aquí se actualizaría el estado en dispatch_events usando trace_id
    return {"status": "ACK received", "trace_id": trace_id}


# ---------------------------------------------------------------------------
# Función auxiliar para transformar la salida del grafo en respuesta SSE
# Usa astream con stream_mode="values" para garantizar checkpoint y streaming real.
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    """
    Genera una cadena SSE con tokens del LLM y contexto técnico al final.
    Prueba de caja negra: BC-T01 (Conversación On-Grid), BC-T02 (Off-Grid).
    """
    config = {"configurable": {"thread_id": thread_id}}
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}
    
    logger.info(f"Ejecutando chat para thread_id={thread_id}")

    async with locks[thread_id]:
        estado_anterior = None
        respuesta_completa = ""
        ctx = {}

        # Usamos astream en lugar de ainvoke para:
        # 1. Obtener streaming en tiempo real (cada token).
        # 2. Garantizar que el checkpoint se actualice al finalizar.
        async for update in graph.astream(estado_inicial, config=config, stream_mode="values"):
            estado_actual = update
            # Extraer último mensaje (puede ser del asistente o del usuario)
            messages = estado_actual.get("messages", [])
            if messages:
                ultimo = messages[-1]
                if isinstance(ultimo, AIMessage):
                    contenido = ultimo.content or ""
                    # Calcular delta entre el contenido anterior y el nuevo
                    if estado_anterior is None:
                        # Primer chunk: enviar todo el contenido
                        if contenido:
                            yield f"data: {json.dumps({'token': contenido})}\n\n"
                            respuesta_completa = contenido
                    else:
                        mensajes_anteriores = estado_anterior.get("messages", [])
                        if mensajes_anteriores:
                            anterior = mensajes_anteriores[-1]
                            contenido_anterior = anterior.content if hasattr(anterior, "content") else ""
                            # Enviar solo la parte nueva
                            if contenido.startswith(contenido_anterior):
                                nuevo = contenido[len(contenido_anterior):]
                                if nuevo:
                                    yield f"data: {json.dumps({'token': nuevo})}\n\n"
                                    respuesta_completa += nuevo
                            else:
                                # Si no es incremental, enviar todo (caso de herramientas o cambios bruscos)
                                if contenido:
                                    yield f"data: {json.dumps({'token': contenido})}\n\n"
                                    respuesta_completa = contenido
                elif isinstance(ultimo, HumanMessage) and estado_anterior is None:
                    # No emitir el mensaje del usuario
                    pass
            estado_anterior = estado_actual

        # Al final, enviar el contexto completo
        ctx = estado_actual.get("contexto_tecnico", {})
        logger.info(f"Contexto final para thread {thread_id}: {ctx}")
        yield f"data: {json.dumps({'contexto_tecnico': ctx})}\n\n"


# ---------------------------------------------------------------------------
# Endpoint principal: chat con streaming (SSE)
# BC-T01 a BC-T10
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=None)
async def chat_streaming(request: ChatRequest):
    """
    Procesa un mensaje del usuario y devuelve la respuesta del agente
    mediante Server‑Sent Events (SSE). Cada token se envía por separado
    para baja latencia percibida.
    """
    try:
        return StreamingResponse(
            generar_tokens(request.thread_id, request.message),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error("Error en /chat: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoints auxiliares (stt, tts, vision, products)
# BC-T06 (OCR factura), BC-T03 (Falla Odoo)
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
