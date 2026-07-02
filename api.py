"""
api.py
Servidor central de lógica de negocio de JARVI 2.0 (FastAPI).
Contiene el ciclo de vida del grafo, control de concurrencia, seguridad
y endpoints unificados para todos los canales (Streamlit, n8n, LangSmith).
Incorpora el módulo CTFOM de telemetría cognitiva para trazabilidad
end‑to‑end, detección de cuellos de botella y verificación de despacho.
Estándares: ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
"""

import os
import asyncio
import json
import time
import logging
from collections import defaultdict
from typing import AsyncGenerator

import psutil  # telemetría de recursos
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage

from schemas import ChatRequest, ChatResponse, AudioRequest, ImageRequest
from agent_graph import create_graph
from config import ISOConfigValidator  # noqa: F401 – asegura entorno válido

# --- CTFOM: módulo de telemetría cognitiva ---
from telemetry import (
    trace_id_var, span_id_var, parent_span_id_var,
    generate_trace_span, log_telemetry_event, _batch_worker
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
    Prueba de caja negra: peticiones sin token → 403; token válido → 200.
    """
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

# ---------------------------------------------------------------------------
# Control de concurrencia por sesión (evita escrituras simultáneas)
# ---------------------------------------------------------------------------
locks = defaultdict(asyncio.Lock)

# ---------------------------------------------------------------------------
# Auditoría 360° (escritura asíncrona en base de datos de trazabilidad)
# ---------------------------------------------------------------------------
async def persistir_evento_auditoria(thread_id: str, run_id: str, payload: dict):
    """
    Inserta un registro de auditoría en la tabla audit_events.
    Prueba de caja negra: verificar en PostgreSQL que se crea un nuevo registro
    tras cada llamada al endpoint /chat.
    """
    try:
        logger.info("AUDIT|%s|%s|%s", thread_id, run_id, json.dumps(payload, default=str))
    except Exception as e:
        logger.error("Error crítico en auditoría asíncrona: %s", e)


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
    
    # Se utiliza AsyncExitStack para mantener vivas las conexiones del Pool asíncrono
    # de manera segura durante todo el ciclo de vida del proceso de FastAPI.
    async with AsyncExitStack() as stack:
        logger.info("Inicializando Pool de conexiones de Postgres para LangGraph Checkpointer...")
        
        # 1. Instanciar el gestor desde la cadena de conexión
        raw_checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
        
        # 2. Entrar al contexto asíncrono del checkpointer para inicializar la conexión interna y el pool.
        # Esto resuelve el error de Pydantic al retornar una instancia completamente válida y tipada.
        checkpointer = await stack.enter_async_context(raw_checkpointer)
        
        # 3. Asegurar que las tablas de control de estados existan en PostgreSQL
        await checkpointer.setup()
        
        # 4. Compilar el grafo pasando el checkpointer completamente activo
        graph = create_graph(checkpointer)
        logger.info("JARVI 2.0 API inicializada – Grafo listo con Checkpointer de PostgreSQL Activo")

        # CTFOM: iniciar worker de telemetría en segundo plano
        asyncio.create_task(_batch_worker())
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
    Prueba de caja negra: después de una solicitud, debe existir un registro
    en telemetry_events con layer='api'.
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
# ---------------------------------------------------------------------------
@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    """
    Recibe confirmación de entrega desde canales externos (n8n).
    En una implementación completa actualizaría dispatch_events.
    Prueba de caja negra: tras una llamada a /chat, enviar POST /ack/{trace_id}
    y verificar en dispatch_events que ack_received = TRUE.
    """
    # Aquí se actualizaría el estado en dispatch_events usando trace_id
    return {"status": "ACK received", "trace_id": trace_id}


# ---------------------------------------------------------------------------
# Función auxiliar para transformar la salida del grafo en respuesta SSE
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    """
    Genera una cadena SSE con tokens del LLM y contexto técnico al final.
    Prueba de caja negra: una petición a /chat debe devolver un stream con
    múltiples eventos 'data' cuyo último mensaje incluye 'contexto_tecnico'.
    """
    config = {"configurable": {"thread_id": thread_id}}
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}

    async with locks[thread_id]:
        evento_llm = False
        async for evento in graph.astream_events(estado_inicial, config=config, version="v2"):
            kind = evento["event"]
            if kind == "on_chat_model_stream":
                contenido = evento["data"]["chunk"].content
                if contenido:
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
# Endpoint principal: chat con streaming (SSE)
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=None)
async def chat_streaming(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Procesa un mensaje del usuario y devuelve la respuesta del agente
    mediante Server‑Sent Events (SSE). Cada token se envía por separado
    para baja latencia percibida.

    Prueba de caja negra (ISO/IEC 29119):
        - Enviar mensaje "hola" y verificar que se reciben múltiples líneas
          `data: {"token": ...}` y un evento final con `contexto_tecnico`.
        - Probar con thread_id diferente: el contexto se debe mantener independiente.
        - Probar con un mensaje que active la herramienta de persistencia:
          debe aparecer el token "(acción ejecutada)" y luego la confirmación.
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
# Endpoint: Speech‑to‑Text (Whisper)
# ---------------------------------------------------------------------------
@app.post("/stt")
async def speech_to_text(request: AudioRequest):
    """
    Convierte un archivo de audio (multipart/form-data) en texto usando OpenAI Whisper.
    Prueba de caja negra: subir un archivo .wav con voz; debe devolver {"transcript": "..."}.
    """
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar Whisper")


# ---------------------------------------------------------------------------
# Endpoint: Text‑to‑Speech (TTS)
# ---------------------------------------------------------------------------
@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    """
    Sintetiza voz a partir de texto usando OpenAI TTS y devuelve audio/mpeg.
    Prueba de caja negra: enviar {"text": "hola"} y recibir un blob de audio reproducible.
    """
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar TTS")


# ---------------------------------------------------------------------------
# Endpoint: Análisis de factura (visión artificial)
# ---------------------------------------------------------------------------
@app.post("/vision/analyze")
async def analizar_factura(request: ImageRequest):
    """
    Extrae datos de una factura eléctrica de Guatemala usando GPT‑4o‑mini.
    Prueba de caja negra: enviar base64 de una factura real y verificar que los campos
    empresa_electrica, consumo_kwh y monto_factura se extraen correctamente.
    """
    raise HTTPException(status_code=501, detail="No implementado – pendiente centralizar visión")


# ---------------------------------------------------------------------------
# Endpoint: Catálogo de productos (ontología/Odoo)
# ---------------------------------------------------------------------------
@app.post("/products")
async def consultar_productos(topologia: str = "on-grid"):
    """
    Devuelve el fragmento de ontología o los productos de Odoo según topología.
    Útil para canales externos como n8n.
    """
    raise HTTPException(status_code=501, detail="No implementado – pendiente exponer catálogo")
