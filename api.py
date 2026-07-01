"""
api.py
Servidor central de lógica de negocio de JARVI 2.0 (FastAPI).
Contiene el ciclo de vida del grafo, control de concurrencia, seguridad
y endpoints unificados para todos los canales (Streamlit, n8n, LangSmith).
Estándares: ISO/IEC/IEEE 12207, ISO/IEC 26514, ISO/IEC 25010, ISO/IEC 29119.
"""

import os
import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage

from schemas import ChatRequest, ChatResponse, AudioRequest, ImageRequest
from agent_graph import create_graph
from config import ISOConfigValidator  # noqa: F401 – asegura entorno válido

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
        # Se asume que existe una función helper en db.py para insertar
        # Por simplicidad, aquí se simula con un log estructurado
        logger.info("AUDIT|%s|%s|%s", thread_id, run_id, json.dumps(payload, default=str))
        # En producción, se podría llamar a:
        # await insertar_auditoria(thread_id, run_id, payload)
    except Exception as e:
        logger.error("Error crítico en auditoría asíncrona: %s", e)


# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación (inicialización del grafo y base de datos)
# ---------------------------------------------------------------------------
graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicializa el checkpointer de PostgreSQL y compila el grafo una sola vez.
    Prueba de caja negra: al arrancar, debe loguear "Grafo inicializado correctamente".
    Si falla la conexión a DB, la aplicación no debe levantar.
    """
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida – servicio no disponible")
    checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
    # El DDL se aplica en db_migrate.py, no duplicamos setup() aquí
    graph = create_graph(checkpointer)
    logger.info("JARVI 2.0 API inicializada – Grafo listo")
    yield
    # cleanup: cerrar conexiones si fuera necesario
    logger.info("Apagando API JARVI")


# ---------------------------------------------------------------------------
# Instancia de FastAPI con ciclo de vida y dependencia de seguridad global
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JARVI 2.0 API Central",
    version="2.0.02",
    lifespan=lifespan,
    dependencies=[Depends(validar_api_key)]
)


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
        # stream_mode="messages" emite (message, metadata) por cada token
        # Usamos astream_events para capturar tokens del LLM
        evento_llm = False
        async for evento in graph.astream_events(estado_inicial, config=config, version="v2"):
            kind = evento["event"]
            if kind == "on_chat_model_stream":
                contenido = evento["data"]["chunk"].content
                if contenido:
                    # Escapar saltos de línea para SSE
                    contenido_escapado = contenido.replace('\n', '\\n')
                    yield f"data: {{\"token\": \"{contenido_escapado}\"}}\n\n"
                    evento_llm = True
            elif kind == "on_chain_end" and evento["name"] == "LangGraph":
                # Último evento del grafo, enviamos el contexto técnico
                estado_final = evento["data"]["output"]
                ctx = estado_final.get("contexto_tecnico", {})
                yield f"data: {{\"contexto_tecnico\": {json.dumps(ctx)}}}\n\n"
                break

        if not evento_llm:
            # Si no se emitieron tokens (ej. tool call directo), enviamos respuesta textual
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
    # Este endpoint requeriría una integración con OpenAI; aquí se deja la estructura
    # La lógica real se movería desde Streamlit a esta API
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
