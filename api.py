"""
api.py - Servidor FastAPI con endpoints /chat y /api/chat/stream.
Unificación por número de WhatsApp (prioritario), fingerprint o thread_id.
run_name forzado al número de WhatsApp cuando existe.
Caso No. basado en los últimos 12 dígitos del thread_id.
Historial completo en Redis.
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
# FUNCIONES DE POSTGRESQL (SOLO GUARDAR RESUMEN FINAL)
# =============================================================================
async def guardar_resumen_postgres(chat_id: str, resumen: str, contexto: dict, fingerprint: Optional[str] = None, origen: str = "desconocido") -> bool:
    try:
        db_url = get_db_url()
        conn = await asyncpg.connect(db_url)
        metadata = contexto.copy()
        metadata["origen"] = origen
        if fingerprint:
            metadata["fingerprint"] = fingerprint
        await conn.execute(
            """
            INSERT INTO resumenes (chat_id, resumen, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, NOW(), NOW())
            ON CONFLICT (chat_id) DO UPDATE
            SET resumen = $2, metadata = $3, updated_at = NOW()
            """,
            chat_id, resumen, json.dumps(metadata)
        )
        await conn.close()
        logger.info(f"Resumen guardado en PostgreSQL para chat_id {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar resumen: {e}")
        return False

# =============================================================================
# FUNCIONES DE BUFFER EN REDIS (SESIONES E HISTORIAL)
# =============================================================================
REDIS_TTL = int(os.getenv("REDIS_TTL", 604800))  # 7 días
HISTORIAL_LIMITE = 64

def sanear_datos_redis(datos: dict) -> dict:
    for key, value in list(datos.items()):
        if value is None:
            if key in ["thread_id", "whatsapp", "nombre", "vendedor", "departamento", "municipio", "topologia", "fase_actual", "ultimo_mensaje", "tipo_producto", "origen", "fingerprint"]:
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

async def guardar_sesion_redis(redis_client: Optional[redis.Redis], chat_id: str, data: dict):
    if not redis_client:
        return
    try:
        key = f"session:{chat_id}"
        data_clean = sanear_datos_redis(data.copy())
        for field in ["contexto_tecnico", "pasos_completados"]:
            if field in data_clean:
                data_clean[field] = json.dumps(data_clean[field])
        await redis_client.hset(key, mapping=data_clean)
        await redis_client.expire(key, REDIS_TTL)
        logger.info(f"Sesión guardada para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error guardando sesión: {e}")

async def obtener_sesion_redis(redis_client: Optional[redis.Redis], chat_id: str) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        key = f"session:{chat_id}"
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
        logger.error(f"Error obteniendo sesión: {e}")
        return None

async def eliminar_sesion_redis(redis_client: Optional[redis.Redis], chat_id: str):
    if redis_client:
        try:
            await redis_client.delete(f"session:{chat_id}")
        except Exception as e:
            logger.error(f"Error eliminando sesión: {e}")

# --- Funciones para el historial ---
async def guardar_historial_redis(redis_client: Optional[redis.Redis], chat_id: str, input_msg: str, output_msg: str):
    if not redis_client:
        return
    try:
        key = f"historial:{chat_id}"
        registro = json.dumps({
            "input": input_msg,
            "output": output_msg,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        })
        await redis_client.lpush(key, registro)
        await redis_client.ltrim(key, 0, HISTORIAL_LIMITE - 1)
        logger.info(f"Historial actualizado para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error guardando historial: {e}")

async def obtener_historial_redis(redis_client: Optional[redis.Redis], chat_id: str) -> list:
    if not redis_client:
        return []
    try:
        key = f"historial:{chat_id}"
        items = await redis_client.lrange(key, 0, -1)
        historial = []
        for item in items:
            try:
                historial.append(json.loads(item))
            except:
                continue
        return historial
    except Exception as e:
        logger.error(f"Error obteniendo historial: {e}")
        return []

async def eliminar_historial_redis(redis_client: Optional[redis.Redis], chat_id: str):
    if redis_client:
        try:
            await redis_client.delete(f"historial:{chat_id}")
        except Exception as e:
            logger.error(f"Error eliminando historial: {e}")

# --- Funciones para mapeo de fingerprint y chat_id ---
async def guardar_fingerprint_redis(redis_client: Optional[redis.Redis], fingerprint: str, chat_id: str):
    if not redis_client:
        return
    try:
        key = f"fingerprint:{fingerprint}"
        await redis_client.set(key, chat_id, ex=REDIS_TTL)
        logger.info(f"Fingerprint {fingerprint} asociado a chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error guardando fingerprint: {e}")

async def obtener_chat_id_por_fingerprint(redis_client: Optional[redis.Redis], fingerprint: str) -> Optional[str]:
    if not redis_client:
        return None
    try:
        key = f"fingerprint:{fingerprint}"
        chat_id = await redis_client.get(key)
        return chat_id
    except Exception as e:
        logger.error(f"Error obteniendo chat_id por fingerprint: {e}")
        return None

async def guardar_whatsapp_redis(redis_client: Optional[redis.Redis], whatsapp: str, chat_id: str):
    if not redis_client:
        return
    try:
        key = f"chat_id:{whatsapp}"
        await redis_client.set(key, chat_id, ex=REDIS_TTL)
        logger.info(f"WhatsApp {whatsapp} asociado a chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Error guardando mapeo whatsapp: {e}")

# =============================================================================
# FUNCIÓN PARA GENERAR RESUMEN CON LLM
# =============================================================================
async def generar_resumen_con_llm(historial: list, contexto: dict) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from agent_graph import DEFAULT_API_KEY
    llm = ChatOpenAI(openai_api_key=DEFAULT_API_KEY, model="gpt-4o-mini")
    prompt = (
        "Resume la siguiente conversación con el cliente, destacando los datos clave "
        "para la preventa de sistemas solares. Incluye nombre, ubicación, necesidades, "
        "tipo de producto (sistema/unitario) y productos de interés.\n\n"
        f"Historial (últimas 64 interacciones):\n{json.dumps(historial, indent=2)}\n\n"
        f"Contexto técnico final:\n{json.dumps(contexto, indent=2)}"
    )
    response = await llm.ainvoke([SystemMessage(content="Eres un asistente especializado en resúmenes de conversaciones de ventas técnicas."),
                                  HumanMessage(content=prompt)])
    return response.content

# =============================================================================
# LÓGICA COMPARTIDA (CORREGIDA)
# =============================================================================
async def process_chat_request(chat_request: ChatRequest, http_request: Request) -> StreamingResponse:
    # 1. Extraer datos
    fingerprint = chat_request.metadata.get("fingerprint") or http_request.headers.get("X-Fingerprint")
    thread_id_from_request = chat_request.thread_id  # UUID original del frontend

    # 2. Extraer número de WhatsApp
    whatsapp_raw = extraer_whatsapp(chat_request.message)
    whatsapp_norm = None
    if whatsapp_raw:
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            logger.info(f"WhatsApp detectado: {whatsapp_norm}")

    # 3. Determinar chat_id (prioridad: número > fingerprint > thread_id)
    chat_id = None
    origen = "desconocido"
    run_name = "Pendiente"

    if whatsapp_norm:
        # PRIORIDAD 1: NÚMERO DE WHATSAPP
        chat_id = whatsapp_norm
        origen = "pantalla" if not chat_request.metadata.get("from_odoo") else "odoo"
        run_name = whatsapp_norm  # Forzamos run_name al número
        if fingerprint and redis_client:
            await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
        logger.info(f"Chat_id asignado por número WhatsApp: {chat_id}")
    elif fingerprint:
        # PRIORIDAD 2: FINGERPRINT
        chat_id_por_fingerprint = await obtener_chat_id_por_fingerprint(redis_client, fingerprint) if redis_client else None
        if chat_id_por_fingerprint:
            chat_id = chat_id_por_fingerprint
            origen = "pantalla"
            logger.info(f"Chat_id recuperado por fingerprint: {chat_id}")
        else:
            chat_id = fingerprint
            origen = "pantalla"
            if redis_client:
                await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
            logger.info(f"Nuevo chat_id generado desde fingerprint: {chat_id}")
    else:
        # PRIORIDAD 3: THREAD_ID (el original del frontend)
        chat_id = thread_id_from_request
        origen = "desconocido"
        logger.info(f"Chat_id asignado desde thread_id: {chat_id}")

    # 4. Obtener o crear sesión en Redis
    sesion_redis = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
    thread_id_final = thread_id_from_request  # Mantenemos el thread_id original

    if sesion_redis:
        # Si la sesión existe, usar su thread_id si es diferente al enviado
        thread_id_guardado = sesion_redis.get("thread_id")
        if thread_id_guardado:
            thread_id_final = thread_id_guardado
        # Actualizar campos si es necesario
        if fingerprint and not sesion_redis.get("fingerprint"):
            sesion_redis["fingerprint"] = fingerprint
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        if whatsapp_norm and sesion_redis.get("whatsapp") != whatsapp_norm:
            sesion_redis["whatsapp"] = whatsapp_norm
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        if origen == "desconocido":
            origen = sesion_redis.get("origen", "desconocido")
        # Forzar run_name al número si existe
        if whatsapp_norm:
            run_name = whatsapp_norm
        else:
            run_name = sesion_redis.get("whatsapp") or thread_id_final
        logger.info(f"Sesión recuperada para chat_id {chat_id} con thread_id {thread_id_final}")
    else:
        # Crear nueva sesión
        data_inicial = {
            "thread_id": thread_id_final,
            "chat_id": chat_id,
            "fingerprint": fingerprint or "",
            "origen": origen,
            "whatsapp": whatsapp_norm or "",
            "nombre": "Pendiente",
            "vendedor": "",
            "departamento": "",
            "municipio": "",
            "topologia": "",
            "tipo_producto": "",
            "contexto_tecnico": {},
            "pasos_completados": [],
            "fase_actual": "inicio",
            "ultimo_mensaje": chat_request.message,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        if redis_client:
            await guardar_sesion_redis(redis_client, chat_id, data_inicial)
            if fingerprint:
                await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
            if whatsapp_norm:
                await guardar_whatsapp_redis(redis_client, whatsapp_norm, chat_id)
        if whatsapp_norm:
            run_name = whatsapp_norm
        else:
            run_name = thread_id_final
        logger.info(f"Nueva sesión creada para chat_id {chat_id} con thread_id {thread_id_final}")

    # 5. Generar respuesta
    return StreamingResponse(
        generar_tokens(thread_id_final, chat_request.message, chat_id, run_name, whatsapp_norm, origen, fingerprint),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Chat-ID": chat_id,
            "X-Thread-ID": thread_id_final,
            "X-Origen": origen,
            "Access-Control-Allow-Origin": "*"
        }
    )

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

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.04",
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

# =============================================================================
# ENDPOINT ORIGINAL /chat (para Odoo y otros clientes)
# =============================================================================
@app.post("/chat")
async def chat_endpoint_original(request: ChatRequest, http_request: Request):
    return await process_chat_request(request, http_request)

# =============================================================================
# ENDPOINT /api/chat/stream (para el frontend de depuración)
# =============================================================================
@app.post("/api/chat/stream")
async def chat_endpoint_stream(request: ChatRequest, http_request: Request):
    return await process_chat_request(request, http_request)

# ---------------------------------------------------------------------------
# Función de generación de tokens (con historial completo y "Caso No.")
# ---------------------------------------------------------------------------
async def generar_tokens(thread_id: str, mensaje: str, chat_id: str, run_name: str | None = None,
                         nuevo_whatsapp: str | None = None, origen: str = "desconocido", fingerprint: str | None = None) -> AsyncGenerator[str, None]:
    trace_id = trace_id_var.get()
    config = {"configurable": {"thread_id": thread_id}}
    config["metadata"] = config.get("metadata", {})
    config["metadata"]["trace_id"] = trace_id
    config["metadata"]["chat_id"] = chat_id
    config["metadata"]["origen"] = origen
    if fingerprint:
        config["metadata"]["fingerprint"] = fingerprint

    # Generar el número de caso (últimos 12 caracteres alfanuméricos del thread_id)
    caso = thread_id.replace('-', '')[-12:] if thread_id else "000000000000"
    mensaje_con_caso = f"{mensaje} [Caso No. {caso}]"
    config["metadata"]["caso"] = caso

    sesion_redis = None
    historial = []
    if redis_client:
        sesion_redis = await obtener_sesion_redis(redis_client, chat_id)
        if sesion_redis:
            historial = await obtener_historial_redis(redis_client, chat_id)
            logger.info(f"Historial recuperado: {len(historial)} mensajes para chat_id {chat_id}")
            # Asegurar run_name: si hay número, usarlo; si no, usar thread_id
            if nuevo_whatsapp:
                run_name = nuevo_whatsapp
            elif not run_name or run_name == "Pendiente":
                run_name = sesion_redis.get("whatsapp") or thread_id
        else:
            logger.warning(f"No hay sesión en Redis para chat_id {chat_id}")

    # Forzar run_name si hay número
    if nuevo_whatsapp:
        run_name = nuevo_whatsapp
    if sesion_redis and sesion_redis.get("whatsapp"):
        run_name = sesion_redis.get("whatsapp")

    # Si no hay número, usar thread_id
    if not run_name or run_name == "Pendiente":
        run_name = thread_id

    config["run_name"] = run_name
    config["metadata"]["whatsapp"] = run_name if run_name != thread_id else ""

    # Construir mensajes con historial (ya incluyen sufijo)
    messages = []
    for item in historial:
        messages.append(HumanMessage(content=item["input"]))
        messages.append(AIMessage(content=item["output"]))
    messages.append(HumanMessage(content=mensaje_con_caso))

    estado_inicial = {
        "messages": messages,
        "contexto_tecnico": sesion_redis.get("contexto_tecnico", {}) if sesion_redis else {}
    }

    async with locks[thread_id]:
        resultado = await graph.ainvoke(estado_inicial, config=config)
        ctx = resultado.get("contexto_tecnico", {})
        logger.info(f"Contexto final: {ctx}")

        respuesta_final = ""
        for msg in reversed(resultado.get("messages", [])):
            if isinstance(msg, AIMessage):
                respuesta_final = msg.content
                break

        # Agregar caso a la respuesta final
        if respuesta_final:
            respuesta_final_con_caso = f"{respuesta_final} [Caso No. {caso}]"
        else:
            respuesta_final_con_caso = f"No se pudo generar respuesta. [Caso No. {caso}]"

        # Guardar historial en Redis (input y output con caso)
        if redis_client and respuesta_final_con_caso:
            await guardar_historial_redis(redis_client, chat_id, mensaje_con_caso, respuesta_final_con_caso)

        # Actualizar sesión en Redis
        if redis_client:
            if not sesion_redis:
                sesion_redis = {}
            sesion_redis["thread_id"] = thread_id
            sesion_redis["chat_id"] = chat_id
            sesion_redis["whatsapp"] = ctx.get("whatsapp") or nuevo_whatsapp or run_name
            sesion_redis["nombre"] = ctx.get("nombre") or sesion_redis.get("nombre", "Pendiente")
            sesion_redis["vendedor"] = ctx.get("vendedor") or sesion_redis.get("vendedor", "")
            sesion_redis["departamento"] = ctx.get("departamento") or sesion_redis.get("departamento", "")
            sesion_redis["municipio"] = ctx.get("municipio") or sesion_redis.get("municipio", "")
            sesion_redis["topologia"] = ctx.get("topologia") or sesion_redis.get("topologia", "")
            sesion_redis["tipo_producto"] = ctx.get("tipo_producto") or sesion_redis.get("tipo_producto", "")
            sesion_redis["contexto_tecnico"] = ctx
            if fingerprint:
                sesion_redis["fingerprint"] = fingerprint
            if origen and origen != "desconocido":
                sesion_redis["origen"] = origen

            pasos = []
            for key in ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]:
                if ctx.get(key):
                    pasos.append(key)
            sesion_redis["pasos_completados"] = pasos
            sesion_redis["fase_actual"] = ctx.get("fase_actual", "conversacion")
            sesion_redis["ultimo_mensaje"] = mensaje_con_caso

            if ctx.get("topologia") and ctx.get("tipo_producto") and not ctx.get("productos_interes"):
                ctx["productos_interes"] = obtener_productos_relevantes(ctx["topologia"], ctx["tipo_producto"], 5)
                logger.info(f"Productos: {ctx['productos_interes']}")

            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)

            pasos_requeridos = ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]
            if all(p in pasos for p in pasos_requeridos) or len(historial) + 1 >= HISTORIAL_LIMITE:
                resumen = await generar_resumen_con_llm(historial, ctx)
                await guardar_resumen_postgres(chat_id, resumen, ctx, fingerprint, origen)
                await eliminar_historial_redis(redis_client, chat_id)
                sesion_redis["fase_actual"] = "completado"
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
                logger.info(f"Resumen guardado en PostgreSQL para chat_id {chat_id}")

        # Enviar respuesta en SSE
        if respuesta_final_con_caso:
            tokens = respuesta_final_con_caso.split()
            for i, token in enumerate(tokens):
                yield f"data: {json.dumps({'token': token + (' ' if i < len(tokens)-1 else '')})}\n\n"
        else:
            yield f"data: {json.dumps({'token': 'No se pudo generar respuesta.'})}\n\n"

        ctx_para_envio = ctx.copy()
        ctx_para_envio.update({
            "chat_id": chat_id,
            "thread_id": thread_id,
            "run_name_actual": run_name,
            "historial_count": len(historial) + 1,
            "origen": origen,
            "fingerprint": fingerprint,
            "caso": caso
        })
        yield f"data: {json.dumps({'contexto_tecnico': ctx_para_envio})}\n\n"

# ---------------------------------------------------------------------------
# ENDPOINT PARA WEBHOOK DE WHATSAPP (API - con pasos ya completos)
# ---------------------------------------------------------------------------
@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict):
    whatsapp = payload.get("number")
    mensaje = payload.get("text")
    datos_cliente = payload.get("datos_cliente", {})

    if not whatsapp or not mensaje:
        raise HTTPException(400, "Faltan campos obligatorios: number y text")

    _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
    if not whatsapp_norm or whatsapp_norm == "Pendiente":
        raise HTTPException(400, "Número de WhatsApp inválido")

    chat_id = whatsapp_norm

    sesion_redis = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
    if sesion_redis:
        run_name = sesion_redis.get("whatsapp") or whatsapp_norm
        if datos_cliente:
            for key in ["nombre", "vendedor", "departamento", "municipio", "topologia", "tipo_producto"]:
                if key in datos_cliente:
                    sesion_redis[key] = datos_cliente[key]
            sesion_redis["contexto_tecnico"] = datos_cliente
            pasos = []
            for p in ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]:
                if sesion_redis.get(p):
                    pasos.append(p)
            sesion_redis["pasos_completados"] = pasos
            sesion_redis["fase_actual"] = "webhook"
            if redis_client:
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
    else:
        run_name = whatsapp_norm
        data_inicial = {
            "thread_id": chat_id,
            "chat_id": chat_id,
            "fingerprint": "",
            "origen": "odoo",
            "whatsapp": whatsapp_norm,
            "nombre": datos_cliente.get("nombre", "Pendiente"),
            "vendedor": datos_cliente.get("vendedor", ""),
            "departamento": datos_cliente.get("departamento", ""),
            "municipio": datos_cliente.get("municipio", ""),
            "topologia": datos_cliente.get("topologia", ""),
            "tipo_producto": datos_cliente.get("tipo_producto", ""),
            "contexto_tecnico": datos_cliente,
            "pasos_completados": ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"] if all(k in datos_cliente for k in ["nombre","whatsapp","departamento","municipio","topologia","tipo_producto"]) else [],
            "fase_actual": "webhook",
            "ultimo_mensaje": mensaje,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        if redis_client:
            await guardar_sesion_redis(redis_client, chat_id, data_inicial)
            await guardar_whatsapp_redis(redis_client, whatsapp_norm, chat_id)

    response_generator = generar_tokens(chat_id, mensaje, chat_id, run_name, origen="odoo")
    respuesta_final = ""
    async for chunk in response_generator:
        if chunk.startswith("data: "):
            try:
                data = json.loads(chunk[6:])
                if "token" in data:
                    respuesta_final += data["token"]
                elif "contexto_tecnico" in data:
                    break
            except:
                pass
    return {"status": "Mensaje procesado", "chat_id": chat_id, "response": respuesta_final}

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
