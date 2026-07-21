# JARVI 2.0.03 | Agente Cognitivo de Preventa Técnica para AISA Solar  
## LangGraph + Langfuse v4.14.1 (SDK Nativo) + OpenTelemetry (Infraestructura)

> **Arquitectura de agente cognitivo con persistencia de estado serializable, orquestación mediante grafos deterministas, gobernanza forense de eventos auditables, canales de consumo desacoplados y telemetría cognitiva de grado industrial. Diseñado para operar en entornos de misión crítica con separación de contextos de datos, resiliencia operacional y trazabilidad completa bajo los estándares ISO/IEC 25010, 27001, 29119 y principios DORA.**

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2.56-purple)
![Langfuse](https://img.shields.io/badge/Langfuse-4.14.1-orange)
![ISO](https://img.shields.io/badge/ISO-25010%20%7C%2027001%20%7C%2029119-blue)
![CTFOM](https://img.shields.io/badge/CTFOM-telemetry-orange)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-1.33.1-lightgrey)
![Status](https://img.shields.io/badge/status-production-brightgreen)

---

## 📋 Tabla de Control de Cambios (Auditoría Técnica)

| Fecha | Versión | Cambio | Responsable |
|-------|---------|--------|-------------|
| 2026-07-21 | 2.0.03 | Documentación inicial | Equipo JARVI |
| 2026-07-21 | 2.0.04 | Corrección de instrumentación Langfuse v4 (SDK nativo) | Ingeniería |
| 2026-07-21 | 2.0.05 | Eliminación de dependencias OpenTelemetry conflictivas | Ingeniería |
| 2026-07-21 | 2.0.06 | Implementación de `propagate_attributes()` para trazabilidad completa | Ingeniería |
| 2026-07-21 | 2.0.07 | Corrección de importación de `CallbackHandler` en Langfuse v4 | Ingeniería |
| 2026-07-21 | 2.0.08 | Robustecimiento de `db_client.py` para manejo de metadatos | Ingeniería |

---

## 📑 Tabla de Contenidos

- [Resumen Ejecutivo](#resumen-ejecutivo)
- [Arquitectura Modular y Topología de Servicios](#arquitectura-modular-y-topología-de-servicios)
- [Instrumentación y Telemetría Cognitiva](#instrumentación-y-telemetría-cognitiva)
  - [CTFOM - Telemetría de Infraestructura](#ctfom---telemetría-de-infraestructura)
  - [Langfuse v4 - Trazabilidad LLM (SDK Nativo)](#langfuse-v4---trazabilidad-llm-sdk-nativo)
- [Diseño de Base de Datos y Gobernanza de Datos](#diseño-de-base-de-datos-y-gobernanza-de-datos)
- [Arquitectura Lógica y Flujos de Información](#arquitectura-lógica-y-flujos-de-información)
- [Variables de Entorno por Servicio](#variables-de-entorno-por-servicio)
- [Canales de Implementación y Consumo](#canales-de-implementación-y-consumo)
- [Pruebas de Caja Negra y Validación Continua](#pruebas-de-caja-negra-y-validación-continua)
- [Gobernanza y Cumplimiento Normativo](#gobernanza-y-cumplimiento-normativo)
- [Stack Tecnológico y Dependencias (Versiones Exactas)](#stack-tecnológico-y-dependencias-versiones-exactas)
- [Referencias Técnicas y Estándares (APA 8ª ed.)](#referencias-técnicas-y-estándares-apa-8ª-ed)
- [Roadmap Estratégico](#roadmap-estratégico)
- [Licencia y Propiedad Intelectual](#licencia-y-propiedad-intelectual)

---

## Resumen Ejecutivo

**JARVI 2.0.03** representa la evolución madura de la arquitectura agéntica de AISA Solar para la preventa técnica de soluciones fotovoltaicas. Esta versión incorpora el módulo **CTFOM (Cognitive Telemetry & Forensic Observability Middleware)** como capa de observabilidad cognitiva profunda, transformando el sistema en una plataforma de inteligencia operacional autoconsciente.

El sistema ha sido rediseñado topológicamente para operar en entornos de producción con tres distritos lógicos completamente aislados:

1. **Distrito Core (JARVI)**: Orquestación del agente conversacional, buffer de sesiones y auditoría de ejecución.
2. **Distrito de Observabilidad (Langfuse v4)**: Trazabilidad nativa de LLM con **SDK propio** (no instrumentación manual OTLP), almacenamiento analítico de alto rendimiento en ClickHouse y colas de procesamiento asíncrono.
3. **Distrito de Inteligencia (BI)**: Almacenamiento de datos de negocio estructurados (leads, resúmenes, hardware) para paneles de control y automatización (n8n).

**Innovación clave de esta versión:** Se ha reemplazado la instrumentación manual de OpenTelemetry para la trazabilidad LLM por el **SDK nativo de Langfuse v4**, que garantiza:
- Tipado correcto de metadatos (`metadata` como objeto, `public` y `bookmarked` como booleanos).
- Propagación automática de `user_id` y `session_id` a todas las observaciones.
- Compatibilidad total con el modelo de datos observations-first de Langfuse v4.
- Eliminación de los errores `ZodError` en el worker de Langfuse.

La separación de contextos (Bounded Contexts) garantiza que las consultas analíticas pesadas no degraden la latencia de la API transaccional, y que los datos de observabilidad no interfieran con la auditoría forense de negocio.

---

## Arquitectura Modular y Topología de Servicios

El sistema se despliega en **Railway** con una topología de microservicios con nombres unívocos y DNS internas dedicadas, eliminando cualquier colisión de responsabilidades.

| Servicio | Rol Ontológico | DNS Interna | Puerto | Dependencias Críticas |
|----------|----------------|-------------|--------|------------------------|
| `jarvi-backend` | Orquestador del agente (FastAPI + LangGraph) | `jarvi-backend.railway.internal` | 8080 | `redis-buffer`, `ctfom-postgres`, `bi-ia-postgres`, Langfuse (externo) |
| `cliente-debug` | Consola de depuración (Flask 3.0.3) | `cliente-debug.railway.internal` | 8081 | `jarvi-backend` (HTTP) |
| `redis-buffer` | Cache de sesiones y estado conversacional | `redis-buffer.railway.internal` | 6379 | Solo `jarvi-backend` |
| `ctfom-postgres` | Base de datos de telemetría y auditoría | `ctfom-postgres.railway.internal` | 5432 | `jarvi-backend`, `telemetry.py` |
| `bi-ia-postgres` | Base de datos de negocio (leads, resúmenes) | `bi-ia-postgres.railway.internal` | 5432 | `jarvi-backend`, `n8n`, `Metabase` |
| `langfuse-web` | Interfaz web de observabilidad (Next.js) | `langfuse-web.railway.internal` | 8080 | `langfuse-postgres`, `langfuse-clickhouse`, `redis-langfuse` |
| `langfuse-worker` | Procesador de trazas en segundo plano | `langfuse-worker.railway.internal` | — | Mismas que `langfuse-web` |
| `redis-langfuse` | Cola de trabajos y caché de API Keys | `redis-langfuse.railway.internal` | 6379 | `langfuse-web`, `langfuse-worker` |
| `langfuse-postgres` | Base de datos relacional de Langfuse | `langfuse-postgres.railway.internal` | 5432 | `langfuse-web`, `langfuse-worker` |
| `langfuse-clickhouse` | Almacenamiento OLAP de trazas | `langfuse-clickhouse.railway.internal` | 8123 | `langfuse-web`, `langfuse-worker` |
| `langfuse-minio` | Almacenamiento de objetos (archivos adjuntos) | `langfuse-minio.railway.internal` | 9000 | `langfuse-web` |

**Observaciones clave de la topología**:
- Cada instancia de Redis tiene un propósito distinto y una DNS única (`redis-buffer` vs `redis-langfuse`), eliminando la ambigüedad y las colisiones de colas.
- Las bases de datos están segregadas por contexto: `ctfom-postgres` para telemetría, `bi-ia-postgres` para negocio, `langfuse-postgres` para observabilidad.
- El servicio `jarvi-langraph-studio` (visualizador de grafos) ha sido eliminado, ya que su funcionalidad está cubierta por la visualización de trazas en Langfuse y la depuración se realiza mediante el endpoint `/debug/routes` y el `cliente-debug`.

---

## Instrumentación y Telemetría Cognitiva

### CTFOM - Telemetría de Infraestructura

El módulo CTFOM proporciona observabilidad profunda sin alterar el comportamiento funcional del agente. Opera en dos niveles:

1. **Telemetría de Infraestructura (CTFOM nativo)**:
   - Captura de eventos de ejecución del grafo con `trace_id`, `span_id`, latencia, CPU, memoria.
   - Registro de despachos a canales externos (webhooks, correos) con verificación de ACK.
   - Monitoreo de salud de servicios (`system_health`) y análisis de causa raíz (`root_cause_analysis`).
   - Persistencia en `ctfom-postgres` mediante worker asíncrono batch.
   - **No utiliza OpenTelemetry para LLM**, solo para métricas de infraestructura.

2. **Trazabilidad LLM (Langfuse v4 - SDK Nativo)**:
   - Captura de prompts, respuestas, tokens y costos de cada llamada a OpenAI.
   - Visualización del flujo de ejecución del grafo en el dashboard de Langfuse.
   - Agrupación por usuario (`user_id` = número de WhatsApp en formato E.164) y sesión (`session_id` = `thread_id`).
   - Almacenamiento en `langfuse-clickhouse` para consultas analíticas de alto rendimiento.
   - **Implementación técnica:**
     - Creación de traza con `langfuse_client.trace(user_id=..., session_id=..., metadata=..., public=False, bookmarked=False)`.
     - Vinculación del `CallbackHandler` mediante `config={"callbacks": [CallbackHandler(trace=trace)]}`.
     - Propagación de atributos mediante el contexto de la traza (no mediante `span.set_attribute`).

### Langfuse v4 - Trazabilidad LLM (SDK Nativo)

**Modelo de Datos Observations-First** (Langfuse, 2026):

> *"Trace attributes such as `user_id`, `session_id`, and `metadata` must be set on all observations. Traces have no separate input and output. Use `propagate_attributes()` to apply attributes to all child observations."*

**Implementación en JARVI 2.0.03**:

```python
# api.py - generar_tokens()
trace = langfuse_client.trace(
    name=f"chat_{caso}",
    user_id=user_id,
    session_id=thread_id,
    tags=["production", origen],
    metadata={
        "chat_id": chat_id,
        "origen": origen,
        "fingerprint": fingerprint or "",
        "caso": caso,
        "whatsapp": user_id
    },
    public=False,
    bookmarked=False
)

langfuse_handler = CallbackHandler(trace=trace)

config = {
    "configurable": {"thread_id": thread_id},
    "callbacks": [langfuse_handler],
    "metadata": {"trace_id": trace.id, "chat_id": chat_id}
}

resultado = await graph.ainvoke(estado_inicial, config=config)
