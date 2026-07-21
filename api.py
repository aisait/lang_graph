"""
api.py
═══════════════════════════════════════════════════════════════════════
Servidor FastAPI con hooks de inyección para CTFOM, Redis y Langfuse.
"""
import os, asyncio, json, time, logging, re, uuid
from collections import defaultdict
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import psutil, asyncpg, redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Depends, Security, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager, AsyncExitStack
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage

# OpenTelemetry
from telemetry_otel import init_telemetry, get_tracer, force_flush
from opentelemetry.trace import Status, StatusCode
from opentelemetry import trace

# Modelos y utilidades
from schemas import ChatRequest, AudioRequest, ImageRequest
from agent_graph import create_graph, normalizar_contacto
from ontology import obtener_productos_relevantes
from telemetry import trace_id_var, span_id_var, generate_trace_span, log_telemetry_event, start_batch_worker
from db_client import get_bi_db_url, get_ctfom_db_url
from utils.sanitize import sanitize_pii, sanitize_dict

logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    voice: str | None = None

API_KEY = os.getenv("CHATBOT_MASTER_API_KEY", "sk_dev_fallback_key")
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
# FUNCIONES DE EXTRACCIÓN DE DATOS (sin cambios)
# =============================================================================
def extraer_whatsapp(mensaje: str) -> str | None:
    # (código sin cambios)
    pass

def extraer_nombre(mensaje: str) -> str | None:
    # (código sin cambios)
    pass

def extraer_ubicacion(mensaje: str) -> tuple:
    from ubicacion import buscar_ubicacion
    resultado = buscar_ubicacion(mensaje)
    if resultado:
        return resultado.get("departamento"), resultado.get("municipio")
    return None, None

def extraer_consumo(mensaje: str) -> str | None:
    # (código sin cambios)
    pass

def extraer_empresa_electrica(mensaje: str) -> str | None:
    # (código sin cambios)
    pass

def extraer_definicion_necesidad(mensaje: str) -> str | None:
    # (código sin cambios)
    pass

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
# FUNCIONES DE POSTGRESQL Y REDIS (sin cambios)
# =============================================================================
async def guardar_resumen_postgres(chat_id: str, resumen: str, contexto: dict, fingerprint=None, origen="desconocido") -> bool:
    # (código sin cambios)
    pass

REDIS_TTL = int(os.getenv("REDIS_TTL", 604800))
HISTORIAL_LIMITE = 64

def serializar_para_redis(valor):
    # (código sin cambios)
    pass

async def guardar_sesion_redis(redis_client, chat_id, data):
    # (código sin cambios)
    pass

async def obtener_sesion_redis(redis_client, chat_id):
    # (código sin cambios)
    pass

async def eliminar_sesion_redis(redis_client, chat_id):
    # (código sin cambios)
    pass

async def guardar_historial_redis(redis_client, chat_id, input_msg, output_msg):
    # (código sin cambios)
    pass

async def obtener_historial_redis(redis_client, chat_id):
    # (código sin cambios)
    pass

async def eliminar_historial_redis(redis_client, chat_id):
    # (código sin cambios)
    pass

async def guardar_fingerprint_redis(redis_client, fingerprint, chat_id):
    # (código sin cambios)
    pass

async def obtener_chat_id_por_fingerprint(redis_client, fingerprint):
    # (código sin cambios)
    pass

async def guardar_whatsapp_redis(redis_client, whatsapp, chat_id):
    # (código sin cambios)
    pass

def asignar_vendedor(productos: list) -> str:
    # (código sin cambios)
    pass

def sanear_db_url(db_url: str) -> str:
    # (código sin cambios)
    pass

def get_db_url() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL no definida")
    return sanear_db_url(raw)

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
        f"Historial:\n{json.dumps(historial, indent=2)}\n\n"
        f"Contexto técnico final:\n{json.dumps(contexto, indent=2)}"
    )
    response = await llm.ainvoke([
        SystemMessage(content="Eres un asistente especializado en resúmenes de conversaciones de ventas técnicas."),
        HumanMessage(content=prompt)
    ])
    return response.content

# =============================================================================
# PROCESAMIENTO DE CHAT Y WEBHOOK (sin cambios)
# =============================================================================
async def process_chat_frontend(chat_request: ChatRequest, http_request: Request) -> StreamingResponse:
    # (código sin cambios, igual que tu versión original)
    pass

async def process_webhook_whatsapp(payload: dict) -> dict:
    # (código sin cambios)
    pass

# =============================================================================
# CICLO DE VIDA DE LA APLICACIÓN
# =============================================================================
graph = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph, redis_client
    telemetry_ok = init_telemetry(app)
    if telemetry_ok:
        logger.info("OpenTelemetry inicializado correctamente")
    else:
        logger.warning("OpenTelemetry desactivado")

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
            logger.warning("REDIS_URL no configurada")

        start_batch_worker()
        yield

    if redis_client:
        await redis_client.close()
    logger.info("Apagando API JARVI")

app = FastAPI(title="JARVI 2.0 API Central", version="2.0.06",
              lifespan=lifespan, dependencies=[Depends(validar_api_key)])

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "jarvi-backend"}

@app.get("/debug/routes")
async def list_routes():
    routes = [{"path": route.path, "methods": list(route.methods)} for route in app.routes]
    return {"routes": routes}

@app.post("/ack/{trace_id}")
async def acknowledge_dispatch(trace_id: str):
    return {"status": "ACK received", "trace_id": trace_id}

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

@app.post("/chat")
async def chat_endpoint_original(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/api/chat/stream")
async def chat_endpoint_stream(request: ChatRequest, http_request: Request):
    return await process_chat_frontend(request, http_request)

@app.post("/webhook/whatsapp")
async def webhook_whatsapp(payload: dict):
    return await process_webhook_whatsapp(payload)

@app.post("/feedback")
async def registrar_feedback(feedback: dict):
    if "trace_id" not in feedback or "value" not in feedback:
        raise HTTPException(status_code=422, detail="trace_id y value son requeridos")
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("user_feedback") as span:
            span.set_attribute("trace.id", feedback["trace_id"])
            span.set_attribute("feedback.name", feedback.get("name", "satisfaccion"))
            span.set_attribute("feedback.value", float(feedback["value"]))
            if feedback.get("comment"):
                span.set_attribute("feedback.comment", feedback["comment"])
        logger.info(f"Feedback registrado para trace_id {feedback['trace_id']}")
        return {"status": "ok", "trace_id": feedback["trace_id"]}
    except Exception as e:
        logger.error(f"Error al registrar feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# FUNCIÓN PRINCIPAL generar_tokens (con hooks de inyección)
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

        # Extracción de datos (nombre, whatsapp, ubicación, etc.)
        # ... (código sin cambios, igual que tu versión original)

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

        # ================================================================
        # HOOK POST-EJECUCIÓN: Cálculo de costos y enriquecimiento
        # ================================================================
        input_tokens = ctx.get("input_tokens", 0)
        output_tokens = ctx.get("output_tokens", 0)
        model = ctx.get("model", "gpt-4o-mini")

        MODEL_PRICES = {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 5.00, "output": 15.00},
        }
        prices = MODEL_PRICES.get(model, {"input": 0.15, "output": 0.60})
        input_cost = input_tokens * prices["input"] / 1_000_000
        output_cost = output_tokens * prices["output"] / 1_000_000
        total_cost = input_cost + output_cost

        root_span.set_attribute("gen_ai.usage.input_cost", input_cost)
        root_span.set_attribute("gen_ai.usage.output_cost", output_cost)
        root_span.set_attribute("gen_ai.usage.total_cost", total_cost)

        if redis_client:
            if not sesion_redis:
                sesion_redis = {}
            telemetry_data = {
                "trace_id": trace_id_ctfom,
                "span_id": span_id_var.get(),
                "llm_cost": total_cost,
                "llm_model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "caso": caso,
            }
            if "contexto_tecnico" not in sesion_redis:
                sesion_redis["contexto_tecnico"] = {}
            sesion_redis["contexto_tecnico"]["telemetry"] = telemetry_data

            for key in ["nombre", "whatsapp", "vendedor", "departamento", "municipio",
                        "topologia", "tipo_producto", "definicion_necesidad",
                        "consumo_actual", "empresa_electrica"]:
                if ctx.get(key):
                    sesion_redis[key] = ctx.get(key)
            if ctx.get("productos_interes"):
                sesion_redis["productos_interes"] = ctx.get("productos_interes")

            await guardar_sesion_redis(redis_client, chat_id, sesion_redis)

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
                cumulative_cost=total_cost
            )

        # ================================================================
        # STREAMING DE RESPUESTA (sin cambios)
        # ================================================================
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
            "resumen": sesion_redis.get("resumen", "") if sesion_redis else "",
            "telemetry": telemetry_data if redis_client else {}
        })
        yield f"data: {json.dumps({'contexto_tecnico': ctx_para_envio})}\n\n"

    try:
        force_flush()
        logger.info("Flush de spans completado")
    except Exception as e:
        logger.error(f"Error en flush final: {e}")

# =============================================================================
# ENDPOINTS AUXILIARES (sin cambios)
# =============================================================================
@app.post("/stt")
async def speech_to_text(request: AudioRequest):
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/vision/analyze")
async def analizar_factura(request: ImageRequest):
    raise HTTPException(status_code=501, detail="No implementado")

@app.post("/products")
async def consultar_productos(topologia: str = "on-grid"):
    raise HTTPException(status_code=501, detail="No implementado")
