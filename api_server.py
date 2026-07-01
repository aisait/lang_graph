"""
api_server.py (backend central JARVI 2.0)
=========================================
Este módulo implementa el servidor FastAPI que centraliza **toda la lógica de negocio**
del agente de preventa técnica de AISA Solar. Los canales (Streamlit, n8n, LangSmith)
son clientes ligeros que consumen exclusivamente esta API.

Estándares aplicados:
  - ISO/IEC/IEEE 12207:2008 (Ciclo de vida del software)
  - ISO/IEC 26514:2021 (Documentación de software)
  - ISO/IEC 25010:2011 (Calidad del producto)
  - ISO/IEC 29119:2022 (Pruebas de software)
"""

import os
import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Security, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage

from schemas import ChatRequest, ChatResponse
from agent_graph import create_graph

# ---------------------------------------------------------------------------
# Configuración de logging (ISO/IEC 26514 – trazabilidad de eventos)
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api_server")


# ---------------------------------------------------------------------------
# Seguridad – autenticación por API Key (ISO/IEC 27001)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def validar_api_key(auth: Optional[str] = Security(api_key_header)):
    """
    Verifica que la cabecera 'Authorization' contenga el token válido.
    Formato esperado: 'Bearer <API_KEY>'.

    Prueba de caja negra (ISO/IEC 29119):
        - Solicitud sin cabecera → 403 Forbidden.
        - Solicitud con token inválido → 403.
        - Solicitud con token correcto → continúa al endpoint.
    """
    expected = f"Bearer {API_KEY}"
    if not auth or auth != expected:
        logger.warning("Intento de acceso no autorizado")
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth


# ---------------------------------------------------------------------------
# Control de concurrencia por sesión (evita escrituras simultáneas)
# ---------------------------------------------------------------------------
locks = defaultdict(asyncio.Lock)  # Un lock por thread_id


# ---------------------------------------------------------------------------
# Auditoría 360° (escritura asíncrona de eventos)
# ---------------------------------------------------------------------------
async def persistir_evento_auditoria(thread_id: str, run_id: str, payload: dict):
    """
    Registra un evento de auditoría en la base de datos (o log estructurado).

    Prueba de caja negra:
        - Llamar al método tras una ejecución del grafo y verificar que el log
          contiene 'AUDIT|{thread_id}|{run_id}|...'.
        - En producción, verificar que la tabla `audit_events` recibe un nuevo registro.
    """
    try:
        logger.info("AUDIT|%s|%s|%s", thread_id, run_id, json.dumps(payload, default=str))
        # En una implementación completa, aquí se haría un INSERT asíncrono en PostgreSQL
    except Exception as e:
        logger.error("Error en auditoría: %s", e)


# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación (ISO/IEC 12207 – inicialización controlada)
# ---------------------------------------------------------------------------
graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inicializa el checkpointer de PostgreSQL y compila el grafo del agente
    exactamente una vez, optimizando recursos (ISO/IEC 25010 – eficiencia).

    Prueba de caja negra:
        - Arrancar la aplicación: debe aparecer el log "JARVI 2.0 API inicializada".
        - Si DATABASE_URL es incorrecta, la aplicación no debe levantar (RuntimeError).
    """
    global graph
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida – servicio no disponible")
    checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
    # El DDL se ejecuta en db_migrate.py, no duplicamos setup() aquí
    graph = create_graph(checkpointer)
    logger.info("JARVI 2.0 API inicializada – Grafo listo")
    yield
    logger.info("Apagando API JARVI")


# ---------------------------------------------------------------------------
# Instancia de FastAPI con dependencia de seguridad global
# ---------------------------------------------------------------------------
app = FastAPI(
    title="JARVI 2.0 API Central",
    version="2.0.02",
    lifespan=lifespan,
    dependencies=[Depends(validar_api_key)]  # Aplica a todos los endpoints
)


# ---------------------------------------------------------------------------
# Endpoint principal: chat con streaming (SSE)
# ---------------------------------------------------------------------------
async def generar_sse(thread_id: str, mensaje: str) -> AsyncGenerator[str, None]:
    """
    Genera un stream Server‑Sent Events (SSE) a partir de la ejecución del grafo.
    Cada token del LLM se emite como un evento separado para minimizar la latencia
    percibida (Time‑to‑First‑Token).

    Prueba de caja negra (ISO/IEC 29119):
        - Enviar un mensaje de prueba; se deben recibir múltiples líneas
          `data: {"token": "..."}\n\n` y un evento final con `"contexto_tecnico"`.
        - Si el mensaje activa la herramienta de persistencia, el flujo debe continuar
          sin bloquearse y la herramienta ejecutarse en segundo plano.
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
                    # Escapar saltos de línea para preservar el formato SSE
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


@app.post("/chat")
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Procesa un mensaje del usuario y retorna la respuesta del agente en tiempo real
    mediante streaming SSE.

    Prueba de caja negra:
        - POST /chat con body {"thread_id": "abc", "message": "Hola"}.
        - El Content‑Type de la respuesta debe ser 'text/event-stream'.
        - Verificar que el cliente recibe tokens progresivamente.
    """
    try:
        return StreamingResponse(
            generar_sse(request.thread_id, request.message),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error("Error en /chat: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno del agente")


# ---------------------------------------------------------------------------
# Endpoint: Speech‑to‑Text (centralización de Whisper)
# ---------------------------------------------------------------------------
@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """
    Recibe un archivo de audio y lo transcribe a texto usando OpenAI Whisper.
    (Pendiente de implementación completa – la lógica se extraerá de la UI)

    Prueba de caja negra:
        - Subir un archivo .wav con voz clara.
        - Esperar respuesta {"transcript": "texto transcrito"}.
    """
    # TODO: Implementar llamada a OpenAI Whisper y devolver transcripción
    raise HTTPException(status_code=501, detail="No implementado – pendiente migrar Whisper desde UI")


# ---------------------------------------------------------------------------
# Endpoint: Text‑to‑Speech (centralización de TTS)
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str = Field(..., description="Texto a convertir en voz")
    voice: str = Field(default="alloy", description="Voz del modelo TTS")

@app.post("/tts")
async def text_to_speech(req: TTSRequest):
    """
    Convierte texto en audio usando OpenAI TTS y devuelve el archivo de audio.

    Prueba de caja negra:
        - POST /tts con {"text": "Hola mundo"}.
        - La respuesta debe ser un blob de audio/mpeg que se pueda reproducir.
    """
    # TODO: Implementar llamada a OpenAI TTS y devolver StreamingResponse de audio
    raise HTTPException(status_code=501, detail="No implementado – pendiente migrar TTS desde UI")


# ---------------------------------------------------------------------------
# Endpoint: Visión (análisis de facturas)
# ---------------------------------------------------------------------------
class ImageRequest(BaseModel):
    thread_id: str = Field(..., description="ID de sesión")
    image_base64: str = Field(..., description="Imagen codificada en base64")

@app.post("/vision/analyze")
async def analizar_factura(request: ImageRequest):
    """
    Analiza una factura eléctrica de Guatemala usando GPT‑4o‑mini y extrae datos.
    (Pendiente de implementación completa – la lógica se extraerá de vision.py)

    Prueba de caja negra:
        - Enviar base64 de una factura real.
        - Verificar que la respuesta incluya 'empresa_electrica', 'consumo_kwh' y 'monto_factura'.
    """
    # TODO: Llamar a la función procesar_imagen_factura de vision.py
    raise HTTPException(status_code=501, detail="No implementado – pendiente migrar visión desde UI")


# ---------------------------------------------------------------------------
# Endpoint: Catálogo de productos (ontología/Odoo)
# ---------------------------------------------------------------------------
@app.get("/products")
async def consultar_productos(topologia: Optional[str] = None):
    """
    Devuelve el fragmento de ontología o los productos de Odoo según topología.
    Permite a canales externos (n8n) obtener información sin pasar por el LLM.

    Prueba de caja negra:
        - GET /products?topologia=on-grid → lista de categorías on‑grid.
        - GET /products (sin parámetro) → lista por defecto.
    """
    # TODO: Integrar obtener_fragmento_ontologia(topologia) y devolver JSON
    raise HTTPException(status_code=501, detail="No implementado – pendiente exponer catálogo")


# ---------------------------------------------------------------------------
# Punto de entrada para ejecución local (solo para desarrollo)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)
