"""
api.py - Servidor FastAPI con checkpointing garantizado.
Unificación de threads por WhatsApp preservando el historial.
Cumple con ISO/IEC 25010, 29119, 27001.
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
from agent_graph import create_graph, normalizar_contacto
from ontology import obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, generate_trace_span, log_telemetry_event, start_batch_worker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Esquemas adicionales
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

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
# FUNCIONES DE UNIFICACIÓN
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

# =============================================================================
# FUNCIÓN PARA SANEAR DATABASE_URL
# =============================================================================
def sanear_db_url(db_url: str) -> str:
    try:
        parsed = urlparse(db_url)
        query = parse_qs(parsed.query)
        for p in ["pool_size", "max_overflow", "pool_timeout"]:
            query.pop(p, None)
        clean_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=clean_query))
    except Exception:
        return db_url

def get_db_url() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL no definida")
    return sanear_db_url(raw)

# =============================================================================
# FUNCIONES DE POSTGRESQL (SOLO PARA DATOS COMPLETOS)
# =============================================================================
async def obtener_thread_por_whatsapp(whatsapp: str) -> str | None:
    try:
        db_url = get_db_url()
        conn = await asyncpg.connect(db_url)
        row = await conn.fetchrow("SELECT thread_id FROM threads WHERE whatsapp_id = $1", whatsapp)
        await conn.close()
        return row["thread_id"] if row else None
    except Exception as e:
        logger.error(f"Error al consultar thread por whatsapp: {e}")
        return None

async def obtener_whatsapp_por_thread(thread_id: str) -> str | None:
    try:
        db_url = get_db_url()
        conn = await asyncpg.connect(db_url)
        row = await conn.fetchrow("SELECT whatsapp_id FROM threads WHERE thread_id = $1", thread_id)
        await conn.close()
        return row["whatsapp_id"] if row else None
    except Exception as e:
        logger.error(f"Error al obtener whatsapp por thread: {e}")
        return None

async def persistir_sesion_postgres(thread_id: str, contexto: dict) -> bool:
    try:
        db_url = get_db_url()
        conn = await asyncpg.connect(db_url)
        nombre = contexto.get("nombre")
        whatsapp = contexto.get("whatsapp")
        vendedor = contexto.get("vendedor")
        departamento = contexto.get("departamento")
        municipio = contexto.get("municipio")
        productos_interes = contexto.get("productos_interes", [])
        tipo_producto = contexto.get("tipo_producto")

        metadata = {
            "nombre": nombre,
            "whatsapp": whatsapp,
            "vendedor": vendedor,
            "departamento": departamento,
            "municipio": municipio,
            "tipo_producto": tipo_producto,
            "productos_interes": productos_interes
        }

        row = await conn.fetchrow("SELECT thread_id FROM threads WHERE thread_id = $1", thread_id)
        if row:
            await conn.execute(
                """
                UPDATE threads
                SET whatsapp_id = $1, nombre_cliente = $2, metadata = $3
                WHERE thread_id = $4
                """,
                whatsapp, nombre, json.dumps(metadata), thread_id
            )
            logger.info(f"Thread {thread_id} actualizado en PostgreSQL")
        else:
            await conn.execute(
                """
                INSERT INTO threads (thread_id, whatsapp_id, nombre_cliente, metadata)
                VALUES ($1, $2, $3, $4)
                """,
                thread_id, whatsapp, nombre, json.dumps(metadata)
            )
            logger.info(f"Thread {thread_id} insertado en PostgreSQL")
        await conn.close()
        return True
    except Exception as e:
        logger.error(f"Error persistiendo sesión en PostgreSQL: {e}")
        return False

# =============================================================================
# FUNCIONES DE BUFFER EN REDIS (SESIONES EN CURSO)
# =============================================================================
REDIS_TTL = int(os.getenv("REDIS_TTL", 604800))  # 7 días

def sanear_datos_redis(datos: dict) -> dict:
    for key, value in list(datos.items()):
        if value is None:
            if key in ["thread_id", "whatsapp", "nombre", "vendedor", "departamento", "municipio", "topologia", "fase_actual", "ultimo_mensaje", "tipo_producto"]:
                datos[key] = ""
            elif key in ["contexto_tecnico", "pasos_completados"]:
                datos[key] = {} if key == "contexto_tecnico" else []
            else:
                datos[key] = ""
        elif isinstance(value, dict):
            datos[key] = sanear_datos_redis(value)
        elif isinstance(value, list):
            datos[key] = [sanear_datos_redis(v) if isinstance(v, dict) else v for v in value]
    return datos

async def guardar_sesion_redis(redis_client: Optional[redis.Redis], identifier: str, data: dict, new_identifier: Optional[str] = None):
    if not redis_client:
        return
    try:
        data_clean = sanear_datos_redis(data.copy())
        for field in ["contexto_tecnico", "pasos_completados"]:
            if field in data_clean:
                data_clean[field] = json.dumps(data_clean[field])

        if new_identifier and new_identifier != identifier:
            old_key = f"session:{identifier}"
            await redis_client.delete(old_key)
            logger.info(f"Clave antigua de Redis eliminada: {old_key}")

        key = f"session:{new_identifier if new_identifier else identifier}"
        await redis_client.hset(key, mapping=data_clean)
        await redis_client.expire(key, REDIS_TTL)
        logger.info(f"Sesión guardada en Redis con clave: {key}")
    except Exception as e:
        logger.error(f"Error guardando sesión en Redis: {e}")

async def obtener_sesion_redis(redis_client: Optional[redis.Redis], identifier: str) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        key = f"session:{identifier}"
        data = await redis_client.hgetall(key)
        if not data:
            return None
        for field in ["contexto_tecnico", "pasos_completados"]:
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = json.loads(data[field])
                except:
                    data[field] = {} if field == "contexto_tecnico" else []
        return data
    except Exception as e:
        logger.error(f"Error obteniendo sesión de Redis: {e}")
        return None

async def eliminar_sesion_redis(redis_client: Optional[redis.Redis], identifier: str):
    if redis_client:
        try:
            await redis_client.delete(f"session:{identifier}")
        except Exception as e:
            logger.error(f"Error eliminando sesión de Redis: {e}")

# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
graph = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, redis_client
    db_url = get_db_url()

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(db_url))
        await checkpointer.setup()
        graph = create_graph(checkpointer)
        logger.info("JARVI 2.0 API inicializada – Grafo listo")
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
# Función de generación de tokens
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str, identifier: str, run_name: str | None = None) -> AsyncGenerator[str, None]:
    trace_id = trace_id_var.get()
    config = {"configurable": {"thread_id": thread_id}}
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["trace_id"] = trace_id

    # 1. Recuperar sesión de Redis usando el identifier (que idealmente es el número)
    sesion_redis = None
    if redis_client and identifier:
        sesion_redis = await obtener_sesion_redis(redis_client, identifier)
        if sesion_redis:
            logger.info(f"Sesión recuperada de Redis para {identifier}")
            # Extraer el run_name de la sesión
            run_name = sesion_redis.get("whatsapp") or run_name or thread_id
            # Obtener el contexto técnico previo
            contexto_previo = sesion_redis.get("contexto_tecnico", {})
        else:
            logger.warning(f"No se encontró sesión en Redis para {identifier}")
    else:
        logger.warning("Redis no disponible o identifier vacío")

    # 2. Si no se encontró en Redis, intentar obtener de PostgreSQL (solo si ya está persistido)
    if not sesion_redis:
        if not run_name or run_name == "Pendiente":
            try:
                whatsapp_actual = await obtener_whatsapp_por_thread(thread_id)
                if whatsapp_actual:
                    run_name = whatsapp_actual
            except Exception as e:
                logger.warning(f"No se pudo obtener whatsapp para run_name: {e}")
        # No hay contexto previo desde Redis
        contexto_previo = {}

    # 3. Si no hay run_name, usar thread_id
    if not run_name or run_name == "Pendiente":
        run_name = thread_id

    # 4. Configurar run_name y metadatos para LangSmith
    config["run_name"] = run_name
    config["metadata"]["whatsapp"] = run_name if run_name != thread_id else ""

    # 5. Preparar el estado inicial con el contexto previo (si existe)
    estado_inicial = {"messages": [HumanMessage(content=mensaje)]}
    if contexto_previo:
        estado_inicial["contexto_tecnico"] = contexto_previo
        logger.info(f"Inyectando contexto previo en el grafo: {contexto_previo}")

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

        # 6. Actualizar Redis con el nuevo contexto
        if redis_client:
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
            if ctx.get("tipo_producto"):
                pasos.append("tipo_producto")

            # Seleccionar productos si tenemos topología y tipo_producto
            if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
                ctx["productos_interes"] = obtener_productos_relevantes(
                    topologia=ctx["topologia"],
                    tipo=ctx["tipo_producto"],
                    max_items=5
                )
                logger.info(f"Productos seleccionados: {ctx['productos_interes']}")

            nuevo_whatsapp = ctx.get("whatsapp")
            if nuevo_whatsapp and nuevo_whatsapp != run_name and nuevo_whatsapp != thread_id:
                run_name = nuevo_whatsapp
                config["run_name"] = run_name
                config["metadata"]["whatsapp"] = run_name

            # Añadir metadatos para LangSmith
            if ctx.get("tipo_producto"):
                config["metadata"]["tipo_producto"] = ctx["tipo_producto"]
            if ctx.get("productos_interes"):
                config["metadata"]["productos_tags"] = [p["tag"] for p in ctx["productos_interes"]]
                config["metadata"]["productos_nombres"] = [p["nombre"] for p in ctx["productos_interes"]]

            data_sesion = {
                "thread_id": thread_id,
                "whatsapp": ctx.get("whatsapp") or run_name,
                "nombre": ctx.get("nombre"),
                "vendedor": ctx.get("vendedor"),
                "departamento": ctx.get("departamento"),
                "municipio": ctx.get("municipio"),
                "topologia": ctx.get("topologia"),
                "tipo_producto": ctx.get("tipo_producto"),
                "contexto_tecnico": ctx,
                "pasos_completados": pasos,
                "fase_actual": ctx.get("fase_actual", "conversacion"),
                "ultimo_mensaje": mensaje,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            # Guardar en Redis; si cambió el número, actualizar la clave
            new_identifier = nuevo_whatsapp if nuevo_whatsapp and nuevo_whatsapp != thread_id else None
            await guardar_sesion_redis(redis_client, identifier, data_sesion, new_identifier=new_identifier)

            # 7. Persistir en PostgreSQL solo si los 6 pasos están completos
            pasos_requeridos = ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]
            if all(p in pasos for p in pasos_requeridos):
                if await persistir_sesion_postgres(thread_id, ctx):
                    await eliminar_sesion_redis(redis_client, new_identifier if new_identifier else identifier)
                    logger.info(f"Sesión finalizada y persistida en PostgreSQL para {thread_id}")

        # 8. Generar respuesta en SSE
        if respuesta_final:
            tokens = respuesta_final.split()
            for i, token in enumerate(tokens):
                yield f"data: {json.dumps({'token': token + (' ' if i < len(tokens)-1 else '')})}\n\n"
        else:
            yield f"data: {json.dumps({'token': 'No se pudo generar una respuesta.'})}\n\n"

        ctx_para_envio = ctx.copy()
        ctx_para_envio["run_name_actual"] = run_name
        yield f"data: {json.dumps({'contexto_tecnico': ctx_para_envio})}\n\n"

# =============================================================================
# ENDPOINT /chat CON UNIFICACIÓN Y BUFFER
# =============================================================================
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # 1. Extraer identificador (prioridad: metadata.whatsapp > metadata.number > thread_id)
    identifier = request.metadata.get("whatsapp") or request.metadata.get("number") or request.thread_id
    run_name = "Pendiente"
    thread_id_final = request.thread_id

    # 2. Intentar recuperar sesión de Redis
    sesion_redis = None
    if redis_client and identifier:
        sesion_redis = await obtener_sesion_redis(redis_client, identifier)
    if sesion_redis:
        thread_id_final = sesion_redis.get("thread_id", request.thread_id)
        run_name = sesion_redis.get("whatsapp") or "Pendiente"
        logger.info(f"Sesión recuperada de Redis para {identifier} con thread {thread_id_final}")
        return StreamingResponse(
            generar_tokens(thread_id_final, request.message, identifier, run_name),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
        )

    # 3. Si no está en Redis, buscar en PostgreSQL (para sesiones ya persistidas)
    whatsapp_raw = extraer_whatsapp(request.message)
    if whatsapp_raw:
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            # Buscar en Redis primero (por si se perdió la conexión temporal)
            if redis_client:
                sesion_redis = await obtener_sesion_redis(redis_client, whatsapp_norm)
                if sesion_redis:
                    thread_id_final = sesion_redis.get("thread_id")
                    run_name = whatsapp_norm
                    logger.info(f"Sesión existente en Redis para {whatsapp_norm} con thread {thread_id_final}")
                    return StreamingResponse(
                        generar_tokens(thread_id_final, request.message, whatsapp_norm, run_name),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                 "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
                    )
            # Si no existe en Redis, buscar en PostgreSQL (datos persistidos)
            existing_thread = await obtener_thread_por_whatsapp(whatsapp_norm)
            if existing_thread:
                thread_id_final = existing_thread
                run_name = whatsapp_norm
                # Recrear en Redis para futuras interacciones
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
                logger.info(f"Thread existente en PostgreSQL {thread_id_final} recuperado para {whatsapp_norm}")
                return StreamingResponse(
                    generar_tokens(thread_id_final, request.message, whatsapp_norm, run_name),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                             "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
                )
            else:
                # Nuevo número: crear en Redis
                new_thread = str(uuid.uuid4())
                thread_id_final = new_thread
                run_name = whatsapp_norm
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
                logger.info(f"Nuevo thread creado en Redis {thread_id_final} para {whatsapp_norm}")
                return StreamingResponse(
                    generar_tokens(thread_id_final, request.message, whatsapp_norm, run_name),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                             "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"}
                )
    else:
        # No hay número: usar thread actual (puede ser nuevo o existente en Redis)
        if redis_client:
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
                logger.info(f"Nuevo thread creado en Redis con thread_id {request.thread_id}")
        run_name = request.thread_id
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
