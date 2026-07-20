"""
api.py - Servidor FastAPI con trazabilidad OpenTelemetry + Langfuse v4.
Cumple con ISO/IEC 27001, DORA, ISO/IEC 25010, ISO/IEC 29119.
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

# Importar OpenTelemetry
from telemetry_otel import init_telemetry, get_tracer

from schemas import ChatRequest, AudioRequest, ImageRequest
from agent_graph import create_graph, normalizar_contacto
from ontology import obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, generate_trace_span, log_telemetry_event, start_batch_worker
from db_client import get_bi_db_url, get_ctfom_db_url

logger = logging.getLogger(__name__)

# =============================================================================
# ESQUEMAS ADICIONALES
# =============================================================================
class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

# =============================================================================
# SEGURIDAD (ISO/IEC 27001)
# =============================================================================
API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

# =============================================================================
# CONTROL DE CONCURRENCIA
# =============================================================================
locks = defaultdict(asyncio.Lock)

# =============================================================================
# TAXONOMÍA DE ERRORES (ISO/IEC 25010 - Mantenibilidad)
# =============================================================================
def taxonomy_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"

# =============================================================================
# FUNCIONES DE EXTRACCIÓN DE DATOS (sin cambios)
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

def extraer_nombre(mensaje: str) -> str | None:
    patrones = [
        r'(?:soy|me llamo|mi nombre es)\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
        r'nombre:\s*([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)',
        r'^([A-Za-zÁÉÍÓÚáéíóúñÑ\s]+)\s*(?:de|quiere|desea)'
    ]
    for patron in patrones:
        match = re.search(patron, mensaje, re.IGNORECASE)
        if match:
            nombre = match.group(1).strip()
            if len(nombre) > 1:
                return nombre
    return None

def extraer_ubicacion(mensaje: str) -> tuple:
    from ubicacion import buscar_ubicacion
    resultado = buscar_ubicacion(mensaje)
    if resultado:
        return resultado.get("departamento"), resultado.get("municipio")
    return None, None

def extraer_consumo(mensaje: str) -> str | None:
    match = re.search(r'consumo\s*(?:de)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:kWh|kw|kwh)', mensaje, re.IGNORECASE)
    if match:
        return f"{match.group(1)} kWh"
    return None

def extraer_empresa_electrica(mensaje: str) -> str | None:
    empresas = [
        "EEGSA", "DEOCSA", "DEORSA",
        "EEM Zacapa", "EEM Gualán", "EEM San Pedro Pinula", "EEM Jalapa",
        "EEM Puerto Barrios", "EEM Guastatoya", "EEM Sayaxché", "EEM Quetzaltenango",
        "EEM Retalhuleu", "EEM San Pedro Sacatepéquez", "EEM Huehuetenango",
        "EEM Joyabaj", "EEM Santa Eulalia", "EEM Tacaná",
        "Empresa Municipal Rural de Electricidad Playa Grande (Ixcán)",
        "EEM San Marcos"
    ]
    for emp in empresas:
        if re.search(r'\b' + re.escape(emp) + r'\b', mensaje, re.IGNORECASE):
            return emp
    return None

def extraer_definicion_necesidad(mensaje: str) -> str | None:
    match = re.search(r'(?:necesito|quiero|deseo|estoy interesado en|busco)\s*(.+?)(?:[\.!?]|$)', mensaje, re.IGNORECASE)
    if match:
        texto = match.group(1).strip()
        palabras = texto.split()[:35]
        return " ".join(palabras)
    return None

def obtener_caso(thread_id: str) -> str:
    return thread_id.replace('-', '')[-12:] if thread_id else "000000000000"

def obtener_run_name(thread_id: str) -> str:
    return obtener_caso(thread_id)

def normalizar_whatsapp_e164(telefono: str) -> str:
    if not telefono:
        return ""
    limpio = re.sub(r'[^\d+]', '', telefono)
    if not limpio.startswith('+'):
        if limpio.startswith('502'):
            limpio = '+' + limpio
        else:
            limpio = '+502' + limpio
    return limpio

# =============================================================================
# FUNCIONES DE POSTGRESQL (sin cambios)
# =============================================================================
async def guardar_resumen_postgres(chat_id: str, resumen: str, contexto: dict,
                                   fingerprint: Optional[str] = None, origen: str = "desconocido") -> bool:
    try:
        db_url = get_bi_db_url()
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
        logger.info(f"Resumen guardado en PostgreSQL (BI) para chat_id {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar resumen: {e}")
        return False

# =============================================================================
# FUNCIONES DE REDIS (sin cambios)
# =============================================================================
REDIS_TTL = int(os.getenv("REDIS_TTL", 604800))
HISTORIAL_LIMITE = 64

def serializar_para_redis(valor):
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    elif isinstance(valor, bool):
        return str(valor).lower()
    elif valor is None:
        return ""
    else:
        return str(valor)

async def guardar_sesion_redis(redis_client: Optional[redis.Redis], chat_id: str, data: dict):
    if not redis_client:
        return
    try:
        key = f"session:{chat_id}"
        data_serialized = {k: serializar_para_redis(v) for k, v in data.items()}
        await redis_client.hset(key, mapping=data_serialized)
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
        for field in ["contexto_tecnico", "pasos_completados", "productos_interes"]:
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = json.loads(data[field])
                except:
                    pass
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
        return await redis_client.get(key)
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
# ASIGNACIÓN DE VENDEDOR (sin cambios)
# =============================================================================
def asignar_vendedor(productos: list) -> str:
    try:
        with open("vendedores.json", "r", encoding="utf-8") as f:
            vendedores = json.load(f)
    except Exception:
        return "default@aisa.com.gt"
    for producto in productos:
        tag = producto.get("tag")
        if tag in vendedores:
            return vendedores[tag]
    return vendedores.get("default", "default@aisa.com.gt")

# =============================================================================
# FUNCIONES DE SANEAMIENTO DE URL (sin cambios)
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
# GENERACIÓN DE RESUMEN CON LLM (sin cambios)
# =============================================================================
async def generar_resumen_con_llm(historial: list, contexto: dict) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from agent_graph import DEFAULT_API_KEY
    llm = ChatOpenAI(openai_api_key=DEFAULT_API_KEY, model="gpt-4o-mini")
    prompt = (
        "Resume la siguiente conversación con el cliente en un máximo de 35 palabras, "
        "destacando los datos clave para la preventa de sistemas solares: "
        "nombre, ubicación, necesidades, tipo de producto (sistema/unitario), "
        "productos de interés, consumo actual, empresa eléctrica, vendedor, etc.\n\n"
        f"Historial (últimas 64 interacciones):\n{json.dumps(historial, indent=2)}\n\n"
        f"Contexto técnico final:\n{json.dumps(contexto, indent=2)}"
    )
    response = await llm.ainvoke([
        SystemMessage(content="Eres un asistente especializado en resúmenes de conversaciones de ventas técnicas."),
        HumanMessage(content=prompt)
    ])
    return response.content

# =============================================================================
# PROCESAMIENTO DE CHAT FRONTEND (sin cambios en lógica, solo spans)
# =============================================================================
async def process_chat_frontend(chat_request: ChatRequest, http_request: Request) -> StreamingResponse:
    fingerprint = chat_request.metadata.get("fingerprint") or http_request.headers.get("X-Fingerprint")
    thread_id_from_request = chat_request.thread_id
    whatsapp_norm = None
    whatsapp_raw = extraer_whatsapp(chat_request.message)
    if whatsapp_raw:
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            logger.info(f"WhatsApp detectado: {whatsapp_norm}")

    chat_id = None
    origen = "pantalla"
    thread_id_final = None

    if fingerprint:
        chat_id_por_fingerprint = await obtener_chat_id_por_fingerprint(redis_client, fingerprint) if redis_client else None
        if chat_id_por_fingerprint:
            chat_id = chat_id_por_fingerprint
            sesion = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
            if sesion:
                thread_id_final = sesion.get("thread_id")
                if not thread_id_final:
                    thread_id_final = str(uuid.uuid4())
                    sesion["thread_id"] = thread_id_final
                    await guardar_sesion_redis(redis_client, chat_id, sesion)
                logger.info(f"Sesión recuperada por fingerprint: {chat_id} con thread {thread_id_final}")
            else:
                thread_id_final = str(uuid.uuid4())
                chat_id = fingerprint
                await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
                logger.info(f"Nueva sesión creada para fingerprint: {chat_id} con thread {thread_id_final}")
        else:
            thread_id_final = str(uuid.uuid4())
            chat_id = fingerprint
            await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
            logger.info(f"Nuevo thread creado para fingerprint: {chat_id} con thread {thread_id_final}")
    else:
        thread_id_final = thread_id_from_request if thread_id_from_request else str(uuid.uuid4())
        chat_id = thread_id_final
        sesion = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
        if not sesion:
            data_inicial = {
                "thread_id": thread_id_final,
                "chat_id": chat_id,
                "fingerprint": "",
                "origen": origen,
                "whatsapp": "",
                "nombre": "Pendiente",
                "vendedor": "",
                "departamento": "",
                "municipio": "",
                "topologia": "",
                "tipo_producto": "",
                "productos_interes": [],
                "contexto_tecnico": {},
                "pasos_completados": [],
                "fase_actual": "inicio",
                "ultimo_mensaje": chat_request.message,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            if redis_client:
                await guardar_sesion_redis(redis_client, chat_id, data_inicial)
            logger.info(f"Nuevo thread forzado (sin fingerprint): {thread_id_final}")
        else:
            logger.info(f"Sesión recuperada por thread_id: {chat_id} con thread {thread_id_final}")

    if whatsapp_norm and chat_id != whatsapp_norm:
        sesion_antigua = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
        if sesion_antigua:
            sesion_antigua["chat_id"] = whatsapp_norm
            sesion_antigua["whatsapp"] = whatsapp_norm
            await guardar_sesion_redis(redis_client, whatsapp_norm, sesion_antigua)
            await eliminar_sesion_redis(redis_client, chat_id)
            if fingerprint:
                await guardar_fingerprint_redis(redis_client, fingerprint, whatsapp_norm)
            chat_id = whatsapp_norm
            logger.info(f"Chat_id actualizado a número: {chat_id}")

    sesion_redis = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
    if not sesion_redis:
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
            "productos_interes": [],
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

    run_name = obtener_run_name(thread_id_final)

    return StreamingResponse(
        generar_tokens(thread_id_final, chat_request.message, chat_id, run_name, whatsapp_norm, origen, fingerprint),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Chat-ID": chat_id,
            "X-Thread-ID": thread_id_final,
            "X-Run-Name": run_name,
            "X-Origen": origen,
            "Access-Control-Allow-Origin": "*"
        }
    )

# =============================================================================
# PROCESAMIENTO DE WEBHOOK WHATSAPP (sin cambios)
# =============================================================================
async def process_webhook_whatsapp(payload: dict) -> dict:
    whatsapp = payload.get("number")
    mensaje = payload.get("text")
    datos_cliente = payload.get("datos_cliente", {})
    chat_id_from_odoo = payload.get("chat_id")

    if not whatsapp or not mensaje:
        raise HTTPException(400, "Faltan campos obligatorios: number y text")

    _, whatsapp_norm = normalizar_contacto("", whatsapp, "")
    if not whatsapp_norm or whatsapp_norm == "Pendiente":
        raise HTTPException(400, "Número de WhatsApp inválido")

    if not chat_id_from_odoo:
        raise HTTPException(400, "chat_id de Odoo es obligatorio")
    chat_id = chat_id_from_odoo

    sesion_redis = await obtener_sesion_redis(redis_client, chat_id) if redis_client else None
    if sesion_redis:
        thread_id = sesion_redis.get("thread_id")
        if not thread_id:
            thread_id = str(uuid.uuid4())
            sesion_redis["thread_id"] = thread_id
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        run_name = obtener_run_name(thread_id)
        if datos_cliente:
            for key in ["nombre", "vendedor", "departamento", "municipio", "topologia", "tipo_producto", "definicion_necesidad", "consumo_actual", "empresa_electrica"]:
                if key in datos_cliente and datos_cliente[key]:
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
        thread_id = str(uuid.uuid4())
        run_name = obtener_run_name(thread_id)
        data_inicial = {
            "thread_id": thread_id,
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
            "productos_interes": [],
            "contexto_tecnico": datos_cliente,
            "pasos_completados": ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"] if all(k in datos_cliente for k in ["nombre","whatsapp","departamento","municipio","topologia","tipo_producto"]) else [],
            "fase_actual": "webhook",
            "ultimo_mensaje": mensaje,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        if redis_client:
            await guardar_sesion_redis(redis_client, chat_id, data_inicial)
            await guardar_whatsapp_redis(redis_client, whatsapp_norm, chat_id)

    response_generator = generar_tokens(thread_id, mensaje, chat_id, run_name, origen="odoo")
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

# =============================================================================
# CICLO DE VIDA DE LA APLICACIÓN (con OpenTelemetry)
# =============================================================================
graph = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, redis_client
    
    # Inicializar OpenTelemetry (sin instrumentación automática)
    telemetry_ok = init_telemetry(app)
    if telemetry_ok:
        logger.info("OpenTelemetry inicializado correctamente")
    else:
        logger.warning("OpenTelemetry desactivado (Langfuse no configurado)")
    
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

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.06",
              lifespan=lifespan, dependencies=[Depends(validar_api_key)])

# =============================================================================
# ENDPOINT DE SALUD
# =============================================================================
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "jarvi-backend"}

# =============================================================================
# ENDPOINT DE DEPURACIÓN DE RUTAS
# =============================================================================
@app.get("/debug/routes")
async def list_routes():
    routes = [{"path": route.path, "methods": list(route.methods)} for route in app.routes]
    return {"routes": routes}

# =============================================================================
# ENDPOINT DE ACKNOWLEDGE
# =============================================================================
@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    return {"status": "ACK received", "trace_id": trace_id}

# =============================================================================
# MIDDLEWARE DE TELEMETRÍA (CTFOM) – se mantiene
# =============================================================================
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

# =============================================================================
# ENDPOINTS PRINCIPALES
# =============================================================================
@app.post("/chat")
async def chat_endpoint_original(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/api/chat/stream")
async def chat_endpoint_stream(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict):
    return await process_webhook_whatsapp(payload)

# =============================================================================
# ENDPOINT DE FEEDBACK (se mantiene, ahora con OpenTelemetry)
# =============================================================================
@app.post("/feedback")
async def registrar_feedback(feedback: dict):
    if "trace_id" not in feedback:
        raise HTTPException(status_code=422, detail="trace_id es requerido")
    if "value" not in feedback:
        raise HTTPException(status_code=422, detail="value es requerido")
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("user_feedback") as span:
            span.set_attribute("trace.id", feedback["trace_id"])
            span.set_attribute("feedback.name", feedback.get("name", "satisfaccion"))
            span.set_attribute("feedback.value", float(feedback["value"]))
            if feedback.get("comment"):
                span.set_attribute("feedback.comment", feedback["comment"])
        
        logger.info(f"Feedback registrado para trace_id {feedback['trace_id']}: {feedback['value']}")
        return {"status": "ok", "trace_id": feedback["trace_id"]}
    except Exception as e:
        logger.error(f"Error al registrar feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Error al registrar feedback: {str(e)}")

# =============================================================================
# FUNCIÓN DE GENERACIÓN DE TOKENS (CON SPANS OPENTELEMETRY)
# =============================================================================
async def generar_tokens(thread_id: str, mensaje: str, chat_id: str, run_name: str | None = None,
                         nuevo_whatsapp: str | None = None, origen: str = "desconocido",
                         fingerprint: str | None = None) -> AsyncGenerator[str, None]:
    tracer = get_tracer()
    
    trace_id_ctfom = trace_id_var.get()
    caso = obtener_caso(thread_id)
    if not run_name:
        run_name = caso

    whatsapp = nuevo_whatsapp or ""
    user_id = normalizar_whatsapp_e164(whatsapp) if whatsapp else chat_id

    with tracer.start_as_current_span("chat_execution") as root_span:
        root_span.set_attribute("user.id", user_id)
        root_span.set_attribute("session.id", thread_id)
        root_span.set_attribute("chat.id", chat_id)
        root_span.set_attribute("fingerprint", fingerprint or "")
        root_span.set_attribute("origen", origen)
        root_span.set_attribute("caso", caso)
        root_span.set_attribute("gen_ai.system", "openai")
        if trace_id_ctfom:
            root_span.set_attribute("ctfom.trace_id", trace_id_ctfom)
        
        config = {
            "configurable": {"thread_id": thread_id},
            "run_name": f"caso_{caso}",
            "metadata": {
                "trace_id": trace_id_ctfom,
                "chat_id": chat_id,
                "origen": origen,
                "caso": caso,
                "fingerprint": fingerprint,
                "whatsapp": user_id
            }
        }

        logger.info(f"Iniciando ejecución para caso {caso} con user_id {user_id}")

        sesion_redis = None
        historial = []
        if redis_client:
            sesion_redis = await obtener_sesion_redis(redis_client, chat_id)
            if sesion_redis:
                historial = await obtener_historial_redis(redis_client, chat_id)
                logger.info(f"Historial recuperado: {len(historial)} mensajes para chat_id {chat_id}")
            else:
                logger.warning(f"No hay sesión en Redis para chat_id {chat_id}")

        nombre = extraer_nombre(mensaje)
        if nombre and (not sesion_redis or not sesion_redis.get("nombre") or sesion_redis.get("nombre") == "Pendiente"):
            if sesion_redis:
                sesion_redis["nombre"] = nombre
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Nombre extraído: {nombre}")

        if nuevo_whatsapp:
            if sesion_redis:
                sesion_redis["whatsapp"] = nuevo_whatsapp
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"WhatsApp actualizado: {nuevo_whatsapp}")

        depto, muni = extraer_ubicacion(mensaje)
        if depto and (not sesion_redis or not sesion_redis.get("departamento")):
            if sesion_redis:
                sesion_redis["departamento"] = depto
                sesion_redis["municipio"] = muni
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Ubicación extraída: {depto}, {muni}")

        consumo = extraer_consumo(mensaje)
        if consumo and (not sesion_redis or not sesion_redis.get("consumo_actual")):
            if sesion_redis:
                sesion_redis["consumo_actual"] = consumo
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Consumo extraído: {consumo}")

        empresa = extraer_empresa_electrica(mensaje)
        if empresa and (not sesion_redis or not sesion_redis.get("empresa_electrica")):
            if sesion_redis:
                sesion_redis["empresa_electrica"] = empresa
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Empresa eléctrica extraída: {empresa}")

        necesidad = extraer_definicion_necesidad(mensaje)
        if necesidad and (not sesion_redis or not sesion_redis.get("definicion_necesidad")):
            if sesion_redis:
                sesion_redis["definicion_necesidad"] = necesidad
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Necesidad extraída: {necesidad}")

        if sesion_redis and sesion_redis.get("productos_interes") and not sesion_redis.get("vendedor"):
            vendedor_email = asignar_vendedor(sesion_redis["productos_interes"])
            sesion_redis["vendedor"] = vendedor_email
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
            logger.info(f"Vendedor asignado: {vendedor_email}")

        mensaje_con_caso = f"{mensaje} [Caso No. {caso}]"

        messages = []
        for item in historial:
            messages.append(HumanMessage(content=item["input"]))
            messages.append(AIMessage(content=item["output"]))
        messages.append(HumanMessage(content=mensaje_con_caso))

        estado_inicial = {
            "messages": messages,
            "contexto_tecnico": sesion_redis.get("contexto_tecnico", {}) if sesion_redis else {}
        }

        with tracer.start_as_current_span("langgraph_execution") as graph_span:
            graph_span.set_attribute("thread_id", thread_id)
            graph_span.set_attribute("message_length", len(mensaje))
            
            async with locks[thread_id]:
                resultado = await graph.ainvoke(estado_inicial, config=config)
                ctx = resultado.get("contexto_tecnico", {})
                logger.info(f"Contexto final: {ctx}")

                respuesta_final = ""
                for msg in reversed(resultado.get("messages", [])):
                    if isinstance(msg, AIMessage):
                        respuesta_final = msg.content
                        break

                if respuesta_final and not respuesta_final.endswith(f"[Caso No. {caso}]"):
                    respuesta_final = f"{respuesta_final} [Caso No. {caso}]"

                graph_span.set_attribute("response_length", len(respuesta_final))
                graph_span.set_status(StatusCode.OK)

        if redis_client and respuesta_final:
            await guardar_historial_redis(redis_client, chat_id, mensaje_con_caso, respuesta_final)

        if redis_client:
            if not sesion_redis:
                sesion_redis = {}
            for key in ["nombre", "whatsapp", "vendedor", "departamento", "municipio",
                        "topologia", "tipo_producto", "definicion_necesidad",
                        "consumo_actual", "empresa_electrica"]:
                if ctx.get(key) and not sesion_redis.get(key):
                    sesion_redis[key] = ctx.get(key)

            if ctx.get("productos_interes"):
                sesion_redis["productos_interes"] = ctx.get("productos_interes")
                if not sesion_redis.get("vendedor"):
                    vendedor_email = asignar_vendedor(ctx["productos_interes"])
                    sesion_redis["vendedor"] = vendedor_email

            if ctx.get("resumen"):
                sesion_redis["resumen"] = ctx.get("resumen")
            elif historial:
                resumen = await generar_resumen_con_llm(historial, ctx)
                sesion_redis["resumen"] = resumen

            sesion_redis["contexto_tecnico"] = ctx
            sesion_redis["thread_id"] = thread_id
            sesion_redis["chat_id"] = chat_id
            if fingerprint:
                sesion_redis["fingerprint"] = fingerprint
            if origen and origen != "desconocido":
                sesion_redis["origen"] = origen

            pasos = []
            for key in ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]:
                if sesion_redis.get(key):
                    pasos.append(key)
            sesion_redis["pasos_completados"] = pasos
            sesion_redis["fase_actual"] = ctx.get("fase_actual", "conversacion")
            sesion_redis["ultimo_mensaje"] = mensaje_con_caso

            if sesion_redis.get("topologia") and sesion_redis.get("tipo_producto") and not sesion_redis.get("productos_interes"):
                productos = obtener_productos_relevantes(sesion_redis["topologia"], sesion_redis["tipo_producto"], 5)
                sesion_redis["productos_interes"] = productos
                ctx["productos_interes"] = productos
                if not sesion_redis.get("vendedor"):
                    vendedor_email = asignar_vendedor(productos)
                    sesion_redis["vendedor"] = vendedor_email

            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)

            pasos_requeridos = ["nombre", "whatsapp", "departamento", "municipio", "topologia", "tipo_producto"]
            if all(p in pasos for p in pasos_requeridos) or len(historial) + 1 >= HISTORIAL_LIMITE:
                resumen = await generar_resumen_con_llm(historial, ctx)
                await guardar_resumen_postgres(chat_id, resumen, ctx, fingerprint, origen)
                await eliminar_historial_redis(redis_client, chat_id)
                sesion_redis["fase_actual"] = "completado"
                await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
                logger.info(f"Resumen guardado en PostgreSQL (BI) para chat_id {chat_id}")

        if respuesta_final:
            tokens = respuesta_final.split()
            for i, token in enumerate(tokens):
                yield f"data: {json.dumps({'token': token + (' ' if i < len(tokens)-1 else '')})}\n\n"
        else:
            yield f"data: {json.dumps({'token': 'No se pudo generar respuesta.'})}\n\n"

        ctx_para_envio = ctx.copy()
        ctx_para_envio.update({
            "chat_id": chat_id,
            "thread_id": thread_id,
            "run_name_actual": run_name,
            "caso": caso,
            "historial_count": len(historial) + 1,
            "origen": origen,
            "fingerprint": fingerprint,
            "nombre": sesion_redis.get("nombre", "Pendiente") if sesion_redis else "Pendiente",
            "whatsapp": sesion_redis.get("whatsapp", "") if sesion_redis else "",
            "vendedor": sesion_redis.get("vendedor", "") if sesion_redis else "",
            "departamento": sesion_redis.get("departamento", "") if sesion_redis else "",
            "municipio": sesion_redis.get("municipio", "") if sesion_redis else "",
            "topologia": sesion_redis.get("topologia", "") if sesion_redis else "",
            "tipo_producto": sesion_redis.get("tipo_producto", "") if sesion_redis else "",
            "productos_interes": sesion_redis.get("productos_interes", []) if sesion_redis else [],
            "definicion_necesidad": sesion_redis.get("definicion_necesidad", "") if sesion_redis else "",
            "consumo_actual": sesion_redis.get("consumo_actual", "") if sesion_redis else "",
            "empresa_electrica": sesion_redis.get("empresa_electrica", "") if sesion_redis else "",
            "resumen": sesion_redis.get("resumen", "") if sesion_redis else ""
        })
        yield f"data: {json.dumps({'contexto_tecnico': ctx_para_envio})}\n\n"

# =============================================================================
# ENDPOINTS AUXILIARES (sin cambios)
# =============================================================================
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
