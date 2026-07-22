"""
api.py - Servidor FastAPI con trazabilidad Langfuse v4 mediante API REST.
VERSIÓN 2.0.07 – Trazabilidad vía REST (sin CallbackHandler).
Cumple con ISO/IEC 25010, 27001, DORA.
"""
import os
import asyncio
import json
import time
import logging
import re
import uuid
import base64
import requests
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
from datetime import datetime, timezone

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage
from langfuse import Langfuse

from telemetry_otel import init_telemetry, get_tracer, force_flush as otel_force_flush
from opentelemetry import trace

from schemas import ChatRequest, AudioRequest, ImageRequest
from agent_graph import create_graph, normalizar_contacto
from ontology import obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, generate_trace_span, log_telemetry_event, start_batch_worker
from db_client import get_bi_db_url, get_ctfom_db_url
from utils.sanitize import sanitize_pii
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

# =============================================================================
# CONFIGURACIÓN DE LANGFUSE
# =============================================================================
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PROJECT_ID = os.getenv("LANGFUSE_PROJECT_ID", "cmrnufyoj0006o902f3nrln43")

# =============================================================================
# SEGURIDAD (ISO/IEC 27001)
# =============================================================================
API_KEY = settings.chatbot_master_api_key
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def validar_api_key(auth: str | None = Security(api_key_header)):
    if not auth or auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    return auth

locks = defaultdict(asyncio.Lock)

def taxonomy_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return f"SWR-API-MED-{exc.status_code}"
    return "SWR-API-UNKNOWN-000"

# =============================================================================
# FUNCIONES AUXILIARES PARA LANGFUSE VÍA API REST
# =============================================================================
def langfuse_basic_auth() -> str:
    """Genera el header Basic Auth para las llamadas a la API de Langfuse."""
    credentials = f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}"
    return base64.b64encode(credentials.encode()).decode()

def crear_traza_langfuse(trace_id: str, name: str, user_id: str, session_id: str,
                         metadata: dict, tags: list = None, public: bool = False,
                         bookmarked: bool = False) -> dict:
    """
    Crea una traza en Langfuse usando la API REST.
    Retorna la respuesta JSON de la API.
    """
    url = f"{LANGFUSE_HOST}/api/public/traces"
    headers = {
        "Authorization": f"Basic {langfuse_basic_auth()}",
        "Content-Type": "application/json"
    }
    payload = {
        "id": trace_id,
        "projectId": LANGFUSE_PROJECT_ID,
        "name": name,
        "userId": user_id,
        "sessionId": session_id,
        "metadata": metadata,
        "tags": tags or [],
        "public": public,
        "bookmarked": bookmarked,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

def actualizar_traza_langfuse(trace_id: str, output: dict, metadata: dict = None):
    """
    Actualiza una traza existente (output y metadata) vía API REST.
    """
    url = f"{LANGFUSE_HOST}/api/public/traces/{trace_id}"
    headers = {
        "Authorization": f"Basic {langfuse_basic_auth()}",
        "Content-Type": "application/json"
    }
    payload = {
        "output": output,
        "metadata": metadata or {}
    }
    resp = requests.patch(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()

def crear_score_langfuse(trace_id: str, name: str, value: float, comment: str = None):
    """Registra un score (feedback) vía API REST."""
    url = f"{LANGFUSE_HOST}/api/public/scores"
    headers = {
        "Authorization": f"Basic {langfuse_basic_auth()}",
        "Content-Type": "application/json"
    }
    payload = {
        "traceId": trace_id,
        "projectId": LANGFUSE_PROJECT_ID,
        "name": name,
        "value": value,
        "comment": comment,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()

# =============================================================================
# FUNCIONES DE EXTRACCIÓN (sin cambios)
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
# FUNCIONES DE POSTGRESQL
# =============================================================================
async def guardar_resumen_postgres(chat_id: str, resumen: str, contexto: dict,
                                   fingerprint: Optional[str] = None, origen: str = "desconocido") -> bool:
    try:
        db_url = get_bi_db_url()
        if not db_url:
            print("BI_DATABASE_URL no configurada")
            return False
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
        print(f"Resumen guardado en PostgreSQL (BI) para chat_id {chat_id}")
        return True
    except Exception as e:
        print(f"Error al guardar resumen: {e}")
        return False

# =============================================================================
# FUNCIONES DE REDIS
# =============================================================================
REDIS_TTL = settings.redis_ttl
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
        print(f"Sesión guardada para chat_id {chat_id}")
    except Exception as e:
        print(f"Error guardando sesión: {e}")

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
        print(f"Error obteniendo sesión: {e}")
        return None

async def eliminar_sesion_redis(redis_client: Optional[redis.Redis], chat_id: str):
    if redis_client:
        try:
            await redis_client.delete(f"session:{chat_id}")
        except Exception as e:
            print(f"Error eliminando sesión: {e}")

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
        print(f"Historial actualizado para chat_id {chat_id}")
    except Exception as e:
        print(f"Error guardando historial: {e}")

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
        print(f"Error obteniendo historial: {e}")
        return []

async def guardar_fingerprint_redis(redis_client: Optional[redis.Redis], fingerprint: str, chat_id: str):
    if not redis_client:
        return
    try:
        key = f"fingerprint:{fingerprint}"
        await redis_client.set(key, chat_id, ex=REDIS_TTL)
        print(f"Fingerprint {fingerprint} asociado a chat_id {chat_id}")
    except Exception as e:
        print(f"Error guardando fingerprint: {e}")

async def obtener_chat_id_por_fingerprint(redis_client: Optional[redis.Redis], fingerprint: str) -> Optional[str]:
    if not redis_client:
        return None
    try:
        key = f"fingerprint:{fingerprint}"
        return await redis_client.get(key)
    except Exception as e:
        print(f"Error obteniendo chat_id por fingerprint: {e}")
        return None

async def guardar_whatsapp_redis(redis_client: Optional[redis.Redis], whatsapp: str, chat_id: str):
    if not redis_client:
        return
    try:
        key = f"chat_id:{whatsapp}"
        await redis_client.set(key, chat_id, ex=REDIS_TTL)
        print(f"WhatsApp {whatsapp} asociado a chat_id {chat_id}")
    except Exception as e:
        print(f"Error guardando mapeo whatsapp: {e}")

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

def sanear_db_url(db_url: str) -> str:
    if not db_url:
        return db_url
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
    if raw:
        return sanear_db_url(raw)
    ctfom_url = os.getenv("CTFOM_DATABASE_URL")
    if ctfom_url:
        print("DATABASE_URL no definida. Usando CTFOM_DATABASE_URL para checkpoints de LangGraph.")
        return sanear_db_url(ctfom_url)
    raise RuntimeError("No se encontró DATABASE_URL ni CTFOM_DATABASE_URL.")

# =============================================================================
# CICLO DE VIDA DE LA APLICACIÓN
# =============================================================================
graph = None
redis_client = None
langfuse_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, redis_client, langfuse_client
    print("=== INICIO DEL LIFESPAN ===")
    telemetry_ok = init_telemetry(app)
    print(f"OpenTelemetry init: {telemetry_ok}")

    # Cliente Langfuse (solo para flush y score)
    try:
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            langfuse_client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=LANGFUSE_HOST
            )
            print("✅ Cliente Langfuse (para flush/score) creado.")
        else:
            print("❌ Langfuse no configurado (faltan keys).")
            langfuse_client = None
    except Exception as e:
        print(f"❌ Error al crear cliente Langfuse: {e}")
        langfuse_client = None

    # Conexión a Postgres y grafo
    db_url = get_db_url()
    print(f"DB URL (sanitizada): {db_url[:50]}...")
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(db_url))
        await checkpointer.setup()
        graph = create_graph(checkpointer)
        print("JARVI 2.0 API inicializada – Grafo listo")

        # Conexión a Redis
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            redis_client = redis.from_url(redis_url, decode_responses=True)
            print("Conexión a Redis establecida")
        else:
            print("REDIS_URL no configurada – buffer de sesión deshabilitado")

        start_batch_worker()
        yield

    # Limpieza
    if redis_client:
        await redis_client.close()
    if langfuse_client:
        print("Flushing Langfuse client...")
        langfuse_client.flush()
        print("Langfuse flush completado")
    print("Apagando API JARVI")

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.07",
              lifespan=lifespan, dependencies=[Depends(validar_api_key)])

# =============================================================================
# MIDDLEWARE DE TELEMETRÍA
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
# HEALTH CHECK
# =============================================================================
@app.get("/health")
async def health_check():
    status = {
        "service": "jarvi-backend",
        "version": "2.0.07",
        "redis": "connected" if redis_client else "disconnected",
        "graph": "ready" if graph else "unavailable",
        "langfuse": "healthy" if langfuse_client else "unavailable",
        "status": "ok"
    }
    return status

# =============================================================================
# ENDPOINTS
# =============================================================================
@app.post("/chat")
async def chat_endpoint(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/api/chat/stream")
async def chat_endpoint_stream(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict):
    return await process_webhook_whatsapp(payload)

@app.post("/feedback")
async def registrar_feedback(feedback: dict):
    if "trace_id" not in feedback:
        raise HTTPException(status_code=422, detail="trace_id es requerido")
    if "value" not in feedback:
        raise HTTPException(status_code=422, detail="value es requerido")
    try:
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            crear_score_langfuse(
                trace_id=feedback["trace_id"],
                name=feedback.get("name", "satisfaccion"),
                value=float(feedback["value"]),
                comment=feedback.get("comment")
            )
            print(f"Feedback registrado para trace_id {feedback['trace_id']}: {feedback['value']}")
        else:
            print("Langfuse no configurado para registrar feedback")
        return {"status": "ok", "trace_id": feedback["trace_id"]}
    except Exception as e:
        print(f"Error al registrar feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Error al registrar feedback: {str(e)}")

# =============================================================================
# PROCESAMIENTO DE CHAT FRONTEND
# =============================================================================
async def process_chat_frontend(chat_request: ChatRequest, http_request: Request) -> StreamingResponse:
    fingerprint = chat_request.metadata.get("fingerprint") or http_request.headers.get("X-Fingerprint")
    thread_id_from_request = chat_request.thread_id
    whatsapp_norm = None
    whatsapp_raw = extraer_whatsapp(chat_request.message)
    if whatsapp_raw:
        _, whatsapp_norm = normalizar_contacto("", whatsapp_raw, "")
        if whatsapp_norm and whatsapp_norm != "Pendiente":
            print(f"WhatsApp detectado: {whatsapp_norm}")

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
                print(f"Sesión recuperada por fingerprint: {chat_id} con thread {thread_id_final}")
            else:
                thread_id_final = str(uuid.uuid4())
                chat_id = fingerprint
                await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
                print(f"Nueva sesión creada para fingerprint: {chat_id} con thread {thread_id_final}")
        else:
            thread_id_final = str(uuid.uuid4())
            chat_id = fingerprint
            await guardar_fingerprint_redis(redis_client, fingerprint, chat_id)
            print(f"Nuevo thread creado para fingerprint: {chat_id} con thread {thread_id_final}")
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
            print(f"Nuevo thread forzado (sin fingerprint): {thread_id_final}")
        else:
            print(f"Sesión recuperada por thread_id: {chat_id} con thread {thread_id_final}")

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
            print(f"Chat_id actualizado a número: {chat_id}")

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

    run_name = obtener_caso(thread_id_final)
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
# PROCESAMIENTO DE WEBHOOK WHATSAPP
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
        run_name = obtener_caso(thread_id)
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
        run_name = obtener_caso(thread_id)
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
# FUNCIÓN DE GENERACIÓN DE TOKENS (CON API REST DE LANGFUSE)
# =============================================================================
async def generar_tokens(thread_id: str, mensaje: str, chat_id: str, run_name: str | None = None,
                         nuevo_whatsapp: str | None = None, origen: str = "desconocido",
                         fingerprint: str | None = None) -> AsyncGenerator[str, None]:
    global langfuse_client
    trace_id_ctfom = trace_id_var.get()
    caso = obtener_caso(thread_id)
    if not run_name:
        run_name = caso

    whatsapp = nuevo_whatsapp or ""
    user_id = normalizar_whatsapp_e164(whatsapp) if whatsapp else chat_id

    # ============================
    # 1. CREAR TRAZA VÍA API REST (sin CallbackHandler)
    # ============================
    trace_id_langfuse = str(uuid.uuid4())
    try:
        crear_traza_langfuse(
            trace_id=trace_id_langfuse,
            name=f"chat_{caso}",
            user_id=user_id,
            session_id=thread_id,
            metadata={
                "chat_id": chat_id,
                "origen": origen,
                "fingerprint": fingerprint or "",
                "caso": caso,
                "whatsapp": user_id
            },
            tags=["production", origen],
            public=False,
            bookmarked=False
        )
        print(f"Traza Langfuse creada vía API REST: {trace_id_langfuse}")
    except Exception as e:
        print(f"❌ Error al crear traza Langfuse vía API: {e}")
        trace_id_langfuse = None

    # ============================
    # 2. PREPARAR SESIÓN Y ESTADO
    # ============================
    sesion_redis = None
    historial = []
    if redis_client:
        sesion_redis = await obtener_sesion_redis(redis_client, chat_id)
        if sesion_redis:
            historial = await obtener_historial_redis(redis_client, chat_id)
            print(f"Historial recuperado: {len(historial)} mensajes para chat_id {chat_id}")

    nombre = extraer_nombre(mensaje)
    if nombre and (not sesion_redis or not sesion_redis.get("nombre") or sesion_redis.get("nombre") == "Pendiente"):
        if sesion_redis:
            sesion_redis["nombre"] = nombre
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Nombre extraído: {nombre}")

    if nuevo_whatsapp:
        if sesion_redis:
            sesion_redis["whatsapp"] = nuevo_whatsapp
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"WhatsApp actualizado: {nuevo_whatsapp}")

    depto, muni = extraer_ubicacion(mensaje)
    if depto and (not sesion_redis or not sesion_redis.get("departamento")):
        if sesion_redis:
            sesion_redis["departamento"] = depto
            sesion_redis["municipio"] = muni
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Ubicación extraída: {depto}, {muni}")

    consumo = extraer_consumo(mensaje)
    if consumo and (not sesion_redis or not sesion_redis.get("consumo_actual")):
        if sesion_redis:
            sesion_redis["consumo_actual"] = consumo
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Consumo extraído: {consumo}")

    empresa = extraer_empresa_electrica(mensaje)
    if empresa and (not sesion_redis or not sesion_redis.get("empresa_electrica")):
        if sesion_redis:
            sesion_redis["empresa_electrica"] = empresa
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Empresa eléctrica extraída: {empresa}")

    necesidad = extraer_definicion_necesidad(mensaje)
    if necesidad and (not sesion_redis or not sesion_redis.get("definicion_necesidad")):
        if sesion_redis:
            sesion_redis["definicion_necesidad"] = necesidad
            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Necesidad extraída: {necesidad}")

    if sesion_redis and sesion_redis.get("productos_interes") and not sesion_redis.get("vendedor"):
        vendedor_email = asignar_vendedor(sesion_redis["productos_interes"])
        sesion_redis["vendedor"] = vendedor_email
        await guardar_sesion_redis(redis_client, chat_id, sesion_redis)
        print(f"Vendedor asignado: {vendedor_email}")

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

    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"caso_{caso}",
        "metadata": {
            "chat_id": chat_id,
            "origen": origen,
            "caso": caso,
            "fingerprint": fingerprint,
            "whatsapp": user_id,
            "langfuse_trace_id": trace_id_langfuse
        }
    }

    # ============================
    # 3. EJECUTAR GRAFO (SIN CALLBACKS)
    # ============================
    async with locks[thread_id]:
        try:
            resultado = await graph.ainvoke(estado_inicial, config=config)
        except Exception as e:
            print(f"❌ Error en ejecución del grafo: {e}")
            yield f"data: {json.dumps({'token': 'Lo siento, ocurrió un error interno. Por favor, intenta de nuevo más tarde.'})}\n\n"
            ctx_error = {
                "chat_id": chat_id,
                "thread_id": thread_id,
                "error": str(e),
                "origen": origen,
                "fingerprint": fingerprint,
                "caso": caso,
                "langfuse_trace_id": trace_id_langfuse
            }
            yield f"data: {json.dumps({'contexto_tecnico': ctx_error})}\n\n"
            return

        ctx = resultado.get("contexto_tecnico", {})

        respuesta_final = ""
        for msg in reversed(resultado.get("messages", [])):
            if isinstance(msg, AIMessage):
                respuesta_final = msg.content
                break

        if respuesta_final and not respuesta_final.endswith(f"[Caso No. {caso}]"):
            respuesta_final = f"{respuesta_final} [Caso No. {caso}]"

    # ============================
    # 4. ACTUALIZAR TRAZA VÍA API REST
    # ============================
    if trace_id_langfuse:
        try:
            actualizar_traza_langfuse(
                trace_id=trace_id_langfuse,
                output={"response": respuesta_final},
                metadata={
                    "chat_id": chat_id,
                    "origen": origen,
                    "caso": caso,
                    "nombre": ctx.get("nombre"),
                    "whatsapp": user_id,
                    "topologia": ctx.get("topologia"),
                    "tipo_producto": ctx.get("tipo_producto")
                }
            )
            print(f"Traza {trace_id_langfuse} actualizada con respuesta final")
        except Exception as e:
            print(f"Error al actualizar traza: {e}")

    # Flush del cliente Langfuse (solo para scores)
    if langfuse_client:
        try:
            langfuse_client.flush()
            print("Flush de Langfuse completado")
        except Exception as e:
            print(f"Error en flush de Langfuse: {e}")

    # Guardar historial y thread en BI
    if respuesta_final:
        await guardar_historial_redis(redis_client, chat_id, mensaje_con_caso, respuesta_final)
        from db_client import actualizar_thread
        await actualizar_thread(
            thread_id=thread_id,
            nombre=ctx.get("nombre", "Pendiente"),
            whatsapp=user_id,
            productos=[p.get("nombre") for p in ctx.get("productos_interes", [])],
            vendedor=ctx.get("vendedor"),
            trace_id=trace_id_ctfom,
            cumulative_cost=0.0,
            metadata_adicional=ctx
        )

    # ============================
    # 5. STREAMING DE RESPUESTA
    # ============================
    if respuesta_final:
        tokens = respuesta_final.split()
        for i, token in enumerate(tokens):
            yield f"data: {json.dumps({'token': token + (' ' if i < len(tokens)-1 else '')})}\n\n"
    else:
        yield f"data: {json.dumps({'token': 'No se pudo generar respuesta.'})}\n\n"

    # Contexto final (incluyendo trace_id de Langfuse)
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
        "resumen": sesion_redis.get("resumen", "") if sesion_redis else "",
        "langfuse_trace_id": trace_id_langfuse
    })
    yield f"data: {json.dumps({'contexto_tecnico': ctx_para_envio})}\n\n"

# =============================================================================
# ENDPOINTS AUXILIARES (PENDIENTES)
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
