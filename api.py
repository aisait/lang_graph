"""
api.py - Servidor FastAPI con buffer de sesión en Redis.
Unifica threads por WhatsApp y mantiene contexto temporal en Redis.
"""

import os
import asyncio
import json
import time
import logging
import re
import uuid
from collections import defaultdict
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psutil
import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage

from schemas import ChatRequest, AudioRequest, ImageRequest
from agent_graph import create_graph, normalizar_contacto, obtener_productos_relevantes
from telemetry import (
    trace_id_var, span_id_var,
    generate_trace_span, log_telemetry_event, start_batch_worker
)

# ---------------------------------------------------------------------------
# Esquemas adicionales
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("jarvi.api")

# ---------------------------------------------------------------------------
# Seguridad
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
# FUNCIONES DE UNIFICACIÓN (PostgreSQL)
# =============================================================================
def extraer_whatsapp(mensaje: str) -> str | None:
    if not mensaje:
        return None
    match = re.search(r'(\+?[0-9]{1,3}[-.\s]?)?[0-9]{4,10}', mensaje)
    if match:
        numero = re.sub(r'[\s\-\.]', '', match.group(0))
        if numero.startswith('+'):
            return numero
        elif len(numero) == 8:
            return f"+502 {numero[:4]}-{numero[4:]}"
        elif len(numero) == 11 and numero.startswith('502'):
            return f"+{numero[:3]} {numero[3:7]}-{numero[7:]}"
        else:
            return f"+502 {numero}"
    return None

async def obtener_thread_por_whatsapp(whatsapp: str) -> str | None:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        row = await conn.fetchrow("SELECT thread_id FROM threads WHERE whatsapp_id = $1", whatsapp)
        await conn.close()
        return row["thread_id"] if row else None
    except Exception as e:
        logger.warning(f"Error al consultar thread por whatsapp: {e}")
        return None

async def obtener_whatsapp_por_thread(thread_id: str) -> str | None:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        row = await conn.fetchrow("SELECT whatsapp_id FROM threads WHERE thread_id = $1", thread_id)
        await conn.close()
        return row["whatsapp_id"] if row else None
    except Exception as e:
        logger.warning(f"Error al obtener whatsapp por thread: {e}")
        return None

async def actualizar_thread_con_whatsapp(thread_id: str, whatsapp: str) -> bool:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        await conn.execute(
            "UPDATE threads SET whatsapp_id = $1 WHERE thread_id = $2 AND (whatsapp_id IS NULL OR whatsapp_id = '')",
            whatsapp, thread_id
        )
        await conn.close()
        logger.info(f"Thread {thread_id} actualizado con WhatsApp {whatsapp}")
        return True
    except Exception as e:
        logger.error(f"Error al actualizar thread con whatsapp: {e}")
        return False

async def guardar_thread_si_no_existe(whatsapp: str, thread_id: str) -> bool:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        row = await conn.fetchrow("SELECT thread_id FROM threads WHERE whatsapp_id = $1", whatsapp)
        if row:
            await conn.close()
            return True
        await conn.execute(
            "INSERT INTO threads (thread_id, whatsapp_id, nombre_cliente, metadata) VALUES ($1, $2, $3, $4)",
            thread_id, whatsapp, "Pendiente", json.dumps({"status": "inicial"})
        )
        await conn.close()
        logger.info(f"Nuevo thread creado y guardado: {thread_id} para {whatsapp}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar thread: {e}")
        return False

# =============================================================================
# FUNCIONES DE BUFFER EN REDIS
# =============================================================================
REDIS_TTL = int(os.getenv("REDIS_TTL", 604800))  # 7 días

async def guardar_sesion_redis(redis_client: Optional[redis.Redis], identifier: str, data: dict):
    if not redis_client:
        return
    key = f"session:{identifier}"
    # Convertir diccionarios anidados a JSON
    for field in ["contexto_tecnico", "pasos_completados"]:
        if field in data and isinstance(data[field], (dict, list)):
            data[field] = json.dumps(data[field])
    await redis_client.hset(key, mapping=data)
    await redis_client.expire(key, REDIS_TTL)

async def obtener_sesion_redis(redis_client: Optional[redis.Redis], identifier: str) -> Optional[dict]:
    if not redis_client:
        return None
    key = f"session:{identifier}"
    data = await redis_client.hgetall(key)
    if not data:
        return None
    # Convertir JSONs anidados de vuelta
    for field in ["contexto_tecnico", "pasos_completados"]:
        if field in data and isinstance(data[field], str):
            try:
                data[field] = json.loads(data[field])
            except:
                pass
    return data

async def eliminar_sesion_redis(redis_client: Optional[redis.Redis], identifier: str):
    if redis_client:
        await redis_client.delete(f"session:{identifier}")

# =============================================================================
# PERSISTENCIA FINAL EN POSTGRESQL
# =============================================================================
async def actualizar_metadatos_thread(thread_id: str, contexto: dict) -> bool:
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        metadata = {
            "nombre": contexto.get("nombre"),
            "whatsapp": contexto.get("whatsapp"),
            "vendedor": contexto.get("vendedor"),
            "departamento": contexto.get("departamento"),
            "municipio": contexto.get("municipio"),
            "productos_interes": contexto.get("productos_interes", [])
        }
        await conn.execute(
            "UPDATE threads SET metadata = $1 WHERE thread_id = $2",
            json.dumps(metadata), thread_id
        )
        await conn.close()
        logger.info(f"Metadatos actualizados para thread {thread_id}")
        return True
    except Exception as e:
        logger.error(f"Error actualizando metadatos: {e}")
        return False

# =============================================================================
# CICLO DE VIDA
# =============================================================================
graph = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, redis_client
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL no definida")
    try:
        parsed = urlparse(db_url)
        query = parse_qs(parsed.query)
        for p in ["pool_size", "max_overflow", "pool_timeout"]:
            query.pop(p, None)
        db_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    except Exception:
        pass
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(db_url))
        await checkpointer.setup()
        graph = create_graph(checkpointer)
        logger.info("JARVI 2.0 API inicializada – Grafo listo")
        # Conexión a Redis
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            redis_client = redis.from_url(redis_url, decode_responses=True)
            logger.info("Conexión a Redis establecida")
        else:
            logger.warning("REDIS_URL no configurada – buffer de sesión deshabilitado")
        start_batch_worker()
        yield
    if redis_client:
        await redis_client.close()
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

@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    return {"status": "ACK received", "trace_id": trace_id}

# ---------------------------------------------------------------------------
# Función de generación de tokens (con buffer Redis)
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str, identifier: str, run_name: str | None = None) -> AsyncGenerator[str, None]:
    trace_id = trace_id_var.get()
    config = {"configurable": {"thread_id": thread_id}}
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["trace_id"] = trace_id

    # Intentar recuperar sesión de Redis para obtener run_name y contexto previo
    sesion_redis = None
    if redis_client:
        sesion_redis = await obtener_sesion_redis(redis_client, identifier)
    if sesion_redis:
        if not run_name or run_name == "Pendiente":
            run_name = sesion_redis.get("whatsapp") or "Pendiente"
        # El contexto previo se puede pasar al estado inicial, pero lo manejamos en la invocación
    else:
        # Si no hay sesión en Redis, intentar obtener de PostgreSQL
        if not run_name or run_name == "Pendiente":
            try:
                conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
                row = await conn.fetchrow("SELECT whatsapp_id FROM threads WHERE thread_id = $1", thread_id)
                await conn.close()
                if row and row["whatsapp_id"]:
                    run_name = row["whatsapp_id"]
            except Exception as e:
                logger.warning(f"No se pudo obtener whatsapp para run_name: {e}")

    if run_name and run_name != "Pendiente":
        config["run_name"] = run_name
        config["metadata"]["whatsapp"] = run_name
    else:
        config["run_name"] = "Usuario"

    # Preparar estado inicial (si hay contexto en Redis, se podría inyectar)
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}
    # Si existe sesión en Redis con contexto_tecnico, se puede pasar como estado inicial
    if sesion_redis and sesion_redis.get("contexto_tecnico"):
        estado_inicial["contexto_tecnico"] = sesion_redis["contexto_tecnico"]

    async with locks[thread_id]:
        resultado = await graph.ainvoke(estado_inicial, config=config)
        messages = resultado.get("messages", [])
        ctx = resultado.get("contexto_tecnico", {})
        logger.info(f"Contexto final para thread {thread_id}: {ctx}")

        respuesta_final = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                respuesta_final = msg.content
                break

        # --- ACTUALIZAR BUFFER EN REDIS ---
        if redis_client:
            # Determinar pasos completados (ejemplo: nombre, whatsapp, departamento, municipio, topologia)
            pasos = []
            if ctx.get("nombre"):
                pasos.append("nombre")
            if ctx.get("whatsapp"):
                pasos.append("whatsapp")
            if ctx.get("departamento"):
                pasos.append("departamento")
            if ctx.get("municipio"):
                pasos.append("municipio")
            if ctx.get("topologia"):
                pasos.append("topologia")

            # Extraer productos si topología está definida
            if ctx.get("topologia") and not ctx.get("productos_interes"):
                ctx["productos_interes"] = obtener_productos_relevantes(ctx["topologia"], max_items=5)

            data_sesion = {
                "thread_id": thread_id,
                "whatsapp": ctx.get("whatsapp") or run_name,
                "nombre": ctx.get("nombre"),
                "vendedor": ctx.get("vendedor"),
                "departamento": ctx.get("departamento"),
                "municipio": ctx.get("municipio"),
                "topologia": ctx.get("topologia"),
                "contexto_tecnico": ctx,
                "pasos_completados": pasos,
                "fase_actual": ctx.get("fase_actual", "conversacion"),
                "ultimo_mensaje": mensaje,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            await guardar_sesion_redis(redis_client, identifier, data_sesion)

            # Si todos los pasos principales están completos, persistir en PostgreSQL y eliminar de Redis
            pasos_requeridos = ["nombre", "whatsapp", "departamento", "municipio", "topologia"]
            if all(p in pasos for p in pasos_requeridos):
                await actualizar_metadatos_thread(thread_id, ctx)
                await eliminar_sesion_redis(redis_client, identifier)
                logger.info(f"Sesión finalizada y persistida en PostgreSQL para {identifier}")

        # Generar respuesta en SSE
        if respuesta_final:
            tokens = respuesta_final.split()
            for i, token in enumerate(tokens):
                yield f"data: {json.dumps({'token': token + (' ' if i < len(tokens)-1 else '')})}\n\n"
        else:
            yield f"data: {json.dumps({'token': 'No se pudo generar una respuesta.'})}\n\n"

        yield f"data: {json.dumps({'contexto_tecnico': ctx})}\n\n"

# =============================================================================
# ENDPOINT /chat CON UNIFICACIÓN Y BUFFER
# =============================================================================
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """Endpoint principal que unifica threads y mantiene buffer en Redis."""
    # 1. Extraer identificador (prioridad: metadata.whatsapp > metadata.number > thread_id)
    identifier = request.metadata.get("whatsapp") or request.metadata.get("number") or request.thread_id
    run_name = "Pendiente"
    thread_id_final = request.thread_id

    # 2. Intentar recuperar sesión de Redis
    sesion_redis = None
    if redis_client:
        sesion_redis = await obtener_sesion_redis(redis_client, identifier)
    if sesion_redis:
        # Usar thread_id de Redis si existe
        thread_id_final = sesion_redis.get("thread_id", request.thread_id)
        run_name = sesion_redis.get("whatsapp") or "Pendiente"
        logger.info(f"Sesión recuperada de Redis para {identifier} con thread {thread_id_final}")
        # Si el thread_id de Redis difiere del request, se redirige
        return StreamingResponse(
            generar_tokens(thread_id_final, request.message, identifier, run_name),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
        )

    # 3. Si no hay sesión en Redis, usar lógica de unificación con PostgreSQL
    whatsapp_raw = extraer_whatsapp(request.message)
    if whatsapp_raw:
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            run_name = whatsapp_norm
            whatsapp_actual = await obtener_whatsapp_por_thread(request.thread_id)
            if whatsapp_actual is None or whatsapp_actual == "":
                await actualizar_thread_con_whatsapp(request.thread_id, whatsapp_norm)
                thread_id_final = request.thread_id
            elif whatsapp_actual == whatsapp_norm:
                thread_id_final = request.thread_id
            else:
                existing = await obtener_thread_por_whatsapp(whatsapp_norm)
                if existing:
                    thread_id_final = existing
                else:
                    new_thread = str(uuid.uuid4())
                    await guardar_thread_si_no_existe(whatsapp_norm, new_thread)
                    thread_id_final = new_thread
            # Guardar en Redis la nueva sesión
            if redis_client:
                data_inicial = {
                    "thread_id": thread_id_final,
                    "whatsapp": whatsapp_norm,
                    "nombre": "Pendiente",
                    "contexto_tecnico": {},
                    "pasos_completados": [],
                    "fase_actual": "inicio",
                    "ultimo_mensaje": request.message,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                await guardar_sesion_redis(redis_client, whatsapp_norm, data_inicial)
            return StreamingResponse(
                generar_tokens(thread_id_final, request.message, identifier, run_name),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                         "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
            )
    else:
        # No se detectó número: usar thread actual, pero registrar en Redis con identifier = thread_id
        if redis_client:
            # Verificar si ya existe sesión para este thread_id
            sesion_existente = await obtener_sesion_redis(redis_client, identifier)
            if not sesion_existente:
                data_inicial = {
                    "thread_id": request.thread_id,
                    "whatsapp": "",
                    "nombre": "Pendiente",
                    "contexto_tecnico": {},
                    "pasos_completados": [],
                    "fase_actual": "inicio",
                    "ultimo_mensaje": request.message,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                await guardar_sesion_redis(redis_client, identifier, data_inicial)
        # Obtener run_name desde PostgreSQL
        whatsapp_del_thread = await obtener_whatsapp_por_thread(request.thread_id)
        if whatsapp_del_thread:
            run_name = whatsapp_del_thread
        thread_id_final = request.thread_id

    return StreamingResponse(
        generar_tokens(thread_id_final, request.message, identifier, run_name),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
    )

# ---------------------------------------------------------------------------
# Endpoints auxiliares (no implementados)
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
