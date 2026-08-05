# JARVI 2.0.19 | Agente Cognitivo de Preventa Técnica para AISA Solar  
## OpenAI API 1.50.0 + LangGraph 0.2.56 + Langfuse 3.9.0 (Ingestión REST) + CTFOM

> **Arquitectura de agente cognitivo con persistencia de estado serializable, orquestación mediante grafos deterministas, gobernanza forense de eventos auditables, canales de consumo desacoplados y telemetría cognitiva de grado industrial. Diseñado para operar en entornos de misión crítica con separación de contextos de datos, resiliencia operacional y trazabilidad completa bajo los estándares ISO/IEC 25010, 27001, 29119 y principios DORA.**

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-green)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2.56-purple)
![Langfuse](https://img.shields.io/badge/Langfuse-3.9.0-orange)
![ISO](https://img.shields.io/badge/ISO-25010%20%7C%2027001%20%7C%2029119-blue)
![CTFOM](https://img.shields.io/badge/CTFOM-telemetry-orange)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-1.33.1-lightgrey)
![Status](https://img.shields.io/badge/status-production-brightgreen)

---

## 📋 Tabla de Control de Cambios (Auditoría Técnica)

| Fecha | Versión | Cambio | Responsable |
|-------|---------|--------|-------------|
| 2026-08-03 | 2.0.19 | Corrección de versión de Langfuse (v3.9.0 real) y alineación de documentación con producción | Equipo JARVI |
| 2026-07-21 | 2.0.08 | Robustecimiento de `db_client.py` para manejo de metadatos | Ingeniería |
| 2026-07-21 | 2.0.07 | Corrección de importación de `CallbackHandler` en Langfuse (obsoleto) | Ingeniería |
| 2026-07-21 | 2.0.06 | Implementación de `propagate_attributes()` (no aplicable en v3) | Ingeniería |
| 2026-07-21 | 2.0.05 | Eliminación de dependencias OpenTelemetry conflictivas | Ingeniería |
| 2026-07-21 | 2.0.04 | Corrección de instrumentación para Langfuse v3 (adaptador REST) | Ingeniería |

---

## 📑 Tabla de Contenidos

- [Resumen Ejecutivo](#resumen-ejecutivo)
- [Arquitectura Modular y Topología de Servicios](#arquitectura-modular-y-topología-de-servicios)
- [Instrumentación y Telemetría Cognitiva](#instrumentación-y-telemetría-cognitiva)
  - [CTFOM - Telemetría de Infraestructura](#ctfom---telemetría-de-infraestructura)
  - [Langfuse v3 - Trazabilidad LLM vía Adaptador REST](#langfuse-v3---trazabilidad-llm-vía-adaptador-rest)
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

**JARVI 2.0.19** es la versión en producción activa de la arquitectura agéntica de AISA Solar para la preventa técnica de soluciones fotovoltaicas. Esta versión incorpora el módulo **CTFOM (Cognitive Telemetry & Forensic Observability Middleware)** como capa de observabilidad cognitiva profunda, transformando el sistema en una plataforma de inteligencia operacional autoconsciente.

El sistema opera en tres distritos lógicos completamente aislados:

1. **Distrito Core (JARVI)**: Orquestación del agente conversacional, buffer de sesiones y auditoría de ejecución.
2. **Distrito de Observabilidad (Langfuse v3)**: Trazabilidad LLM mediante un **adaptador REST personalizado (`LangfuseIngestionAdapter`)** que envía eventos al endpoint `/api/public/ingestion`, con almacenamiento en ClickHouse y colas de procesamiento asíncrono (Redis).
3. **Distrito de Inteligencia (BI)**: Almacenamiento de datos de negocio estructurados (leads, resúmenes, hardware) para paneles de control y automatización (n8n).

**Innovación de esta versión:** Se ha reemplazado la instrumentación manual de OpenTelemetry para la trazabilidad LLM por un **adaptador propio (`LangfuseIngestionAdapter`)** que garantiza:
- Envío de eventos en el formato esperado por la Ingestión API de Langfuse v3.
- Separación de responsabilidades: la API REST solo encola eventos; el worker los procesa y persiste en ClickHouse.
- Control total sobre el formato de metadatos y la propagación de `user_id` y `session_id`.
- Eliminación de dependencias del SDK de Langfuse v4, que no está instalado en producción.

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
| `langfuse-minio` | Almacenamiento de objetos (archivos adjuntos y eventos) | `langfuse-minio.railway.internal` | 9000 | `langfuse-web`, `langfuse-worker` |

**Observaciones clave de la topología**:
- Cada instancia de Redis tiene un propósito distinto y una DNS única (`redis-buffer` vs `redis-langfuse`), eliminando la ambigüedad y las colisiones de colas.
- Las bases de datos están segregadas por contexto: `ctfom-postgres` para telemetría, `bi-ia-postgres` para negocio, `langfuse-postgres` para observabilidad.
- El servicio `langfuse-minio` (MinIO) está configurado para almacenar eventos y archivos multimedia, con variables dedicadas (`LANGFUSE_S3_EVENT_UPLOAD_*`).

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

2. **Trazabilidad LLM (Langfuse v3 - Adaptador REST)**:
   - Captura de prompts, respuestas, tokens y costos de cada llamada a OpenAI mediante el adaptador `LangfuseIngestionAdapter`.
   - Visualización del flujo de ejecución del grafo en el dashboard de Langfuse.
   - Agrupación por usuario (`user_id` = número de WhatsApp en formato E.164) y sesión (`session_id` = `thread_id`).
   - Almacenamiento en `langfuse-clickhouse` para consultas analíticas de alto rendimiento.
   - **Implementación técnica:**
     - Creación de traza mediante evento `trace-create` al endpoint `/api/public/ingestion`.
     - Vinculación de observaciones mediante `observation-create` y generaciones mediante `generation-create`.
     - Los eventos se encolan en Redis y el worker los procesa en segundo plano.
     - El adaptador maneja la autenticación Basic Auth con las claves pública/privada de Langfuse.

### Langfuse v3 - Trazabilidad LLM (Adaptador REST)

**Modelo de Datos basado en Ingestión API** (Langfuse v3):

> *"The Ingestion API accepts batches of events (`trace-create`, `observation-create`, `generation-create`, `score-create`) and processes them asynchronously. Traces and observations are stored in ClickHouse; metadata is stored in PostgreSQL."*

### Coexistencia de CTFOM y Langfuse

-   ****CTFOM**** se enfoca en la salud del sistema y auditoría de negocio.
-   ****Langfuse**** se enfoca en la calidad de la respuesta del LLM y el análisis de costos.
-   Ambos sistemas son ****complementarios**** y no comparten infraestructura de datos.

## Diseño de Base de Datos y Gobernanza de Datos

El esquema de bases de datos está completamente separado por contexto, siguiendo los principios de Domain-Driven Design y segregación de responsabilidades.

### 1\. CTFOM Database (ctfom-postgres)

Contiene tablas de telemetría, auditoría y persistencia de estados del grafo:

-   `telemetry_events`: eventos de ejecución (trace\_id, span\_id, latencia, CPU, memoria, metadata).
-   `dispatch_events`: verificación de envíos a canales externos.
-   `system_health`: estado de los servicios (heartbeat, latencia promedio, tasa de error).
-   `root_cause_analysis`: análisis de fallos agregados.
-   `checkpoints` y `checkpoint_blobs`: persistencia de estados de LangGraph.
-   `audit_events`: auditoría de acciones de negocio (creación de oportunidades, etc.).

### 2\. BI Database (bi-ia-postgres)

Almacena los datos de negocio estructurados que alimentan los paneles de inteligencia y la automatización:

-   `threads`: información de clientes (nombre\_cliente, whatsapp\_id, chat\_id, fingerprint, metadata con cumulative\_cost).
-   `resumenes`: resúmenes de conversaciones con metadatos de negocio (origen, fingerprint, etc.).

### 3\. Langfuse Database (langfuse-postgres)

Gestionada por el propio Langfuse (Prisma). Contiene metadatos de usuarios, proyectos, API keys y configuración de la plataforma. ****No debe ser modificada por el código de JARVI.****

### 4\. ClickHouse (langfuse-clickhouse)

Almacena las trazas LLM (observaciones) en formato OLAP para consultas analíticas rápidas. Es el repositorio principal de la observabilidad de Langfuse.

****Tablas críticas en ClickHouse****:

-   `traces`: datos principales de trazas (264 registros en producción).
-   `observations`: observaciones asociadas a trazas (150 en producción).
-   `analytics_traces` y `analytics_observations`: tablas utilizadas por la UI de Langfuse v3 (pueden estar vacías si no se ha configurado `LANGFUSE_ENABLE_EVENTS_TABLE_UI=true`).
-   `events`: tabla opcional que puede ser utilizada por la UI si se habilita la variable correspondiente.

> ****⚠️ Nota:**** En Langfuse v3, la tabla `events` no se crea automáticamente. Si se desea usar la UI con `events`, debe crearse manualmente (ver Playbook de Recuperación).

### Política de migración

-   Un único script (`db_migrate_unificado.py`) maneja la creación de tablas en ambas bases de datos (CTFOM y BI) utilizando variables de entorno `CTFOM_DATABASE_URL` y `BI_DATABASE_URL`.
-   Las migraciones son idempotentes y se ejecutan en orden: primero CTFOM, luego BI.
-   El script incluye función `sanear_db_url()` para eliminar parámetros `pool_size` no compatibles con `asyncpg`.

## Arquitectura Lógica y Flujos de Información

```mermaid

flowchart TD
    subgraph Core[JARVI Core]
        User -->|HTTP/WebSocket| cli-debug[cliente-debug]
        cli-debug --> API[api.py: FastAPI]
        User --> API
        n8n -->|Webhook| API
        API --> CTFOM[CTFOM Middleware]
        CTFOM --> LangGraph[agent_graph.py]
        LangGraph --> Ontology[ontology.py]
        LangGraph --> Checkpoints[(PostgreSQL Checkpoints)]
        LangGraph --> Odoo[odoo_client.py]
        API --> TelemetryWorker[telemetry.py]
        TelemetryWorker --> CTFOMDB[(ctfom-postgres)]
        API --> BI[(bi-ia-postgres)]
    end

    subgraph Obs[Observabilidad]
        LangGraph -->|Adaptador REST| LangfuseAdapter[LangfuseIngestionAdapter]
        LangfuseAdapter -->|HTTP API| LangfuseWeb[langfuse-web]
        LangfuseAdapter -->|HTTP API| LangfuseWorker[langfuse-worker]
        LangfuseWorker --> ClickHouse[(langfuse-clickhouse)]
        LangfuseWorker --> RedisLangfuse[(redis-langfuse)]
        LangfuseWeb --> RedisLangfuse
    end

    subgraph BI[Inteligencia de Negocio]
        BI --> Metabase[bi-la-metabase]
        BI --> n8n
    end
```
  

### Flujo de información detallado

1.  ****Usuario → API****: El mensaje llega al endpoint `/chat` (frontend) o `/webhook/whatsapp` (n8n). La API extrae el `fingerprint` y el `chat_id`, y gestiona la sesión en `redis-buffer`.
2.  ****API → LangGraph****: La API invoca el grafo de LangGraph con el estado conversacional (`messages` y `contexto_tecnico`). El grafo ejecuta los nodos de clasificación, validación, selección de productos y generación de respuesta.
3.  ****LangGraph → CTFOM****: Cada nodo está decorado con `@observe_node`, que registra eventos en `telemetry.py`. El worker asíncrono inserta los eventos en `ctfom-postgres`.
4.  ****LangGraph → Langfuse****: El adaptador `LangfuseIngestionAdapter` captura cada ejecución del grafo (prompts, respuestas, tokens, costos) y los envía a la API HTTP de Langfuse (no mediante OTLP). Las trazas se almacenan en `langfuse-clickhouse` y los metadatos en `langfuse-postgres`.
5.  ****API → BI****: Los resúmenes de conversaciones y los datos de los clientes se guardan en `bi-ia-postgres` (tablas `resumenes` y `threads`). Esta información es consumida por Metabase para dashboards de negocio y por n8n para automatización de leads.
6.  ****API → Redis****: El estado conversacional (sesión, historial) se almacena en `redis-buffer` con TTL de 7 días, permitiendo recuperar el contexto en conversaciones multi-turno.

### Observabilidad transversal

-   ****CTFOM****: Captura eventos de infraestructura y auditoría en `ctfom-postgres`.
-   ****Langfuse****: Captura trazas LLM en `langfuse-clickhouse`.
-   Ambos sistemas utilizan el mismo `thread_id` y `user_id` para correlacionar eventos de negocio con trazas de LLM.

## Variables de Entorno por Servicio

| Servicio        | Variables Clave                            | Valor / Referencia                                                    |
| --------------- | ------------------------------------------ | --------------------------------------------------------------------- |
| jarvi-backend   | PORT                                       | 8080                                                                  |
|                 | CHATBOT_MASTER_API_KEY                     | sk_... (obligatoria)                                                  |
|                 | OPENAI_API_KEY                             | sk-... (o OPENAI_API_KEY_1, _2, _3)                                   |
|                 | CTFOM_DATABASE_URL                         | postgresql://...@ctfom-postgres.railway.internal:5432/...             |
|                 | BI_DATABASE_URL                            | postgresql://...@bi-ia-postgres.railway.internal:5432/...             |
|                 | REDIS_URL                                  | redis://:${REDISPASSWORD}@redis-buffer.railway.internal:6379/0        |
|                 | LANGFUSE_PUBLIC_KEY                        | pk-lf-... (obligatoria para trazabilidad)                             |
|                 | LANGFUSE_SECRET_KEY                        | sk-lf-... (obligatoria para trazabilidad)                             |
|                 | LANGFUSE_HOST                              | https://langfuse-web-production-2599.up.railway.app                   |
|                 | LANGFUSE_TRACING_ENVIRONMENT               | production                                                            |
| langfuse-web    | DATABASE_URL                               | (langfuse-postgres)                                                   |
|                 | CLICKHOUSE_URL                             | http://langfuse-clickhouse.railway.internal:8123                      |
|                 | CLICKHOUSE_MIGRATION_URL                   | clickhouse://langfuse-clickhouse.railway.internal:9000                |
|                 | REDIS_CONNECTION_STRING                    | redis://default:${REDISPASSWORD}@redis-langfuse.railway.internal:6379 |
|                 | NEXTAUTH_URL                               | https://langfuse-web-production-2599.up.railway.app                   |
|                 | NEXTAUTH_SECRET                            | (generado)                                                            |
|                 | SALT                                       | (generado)                                                            |
|                 | ENCRYPTION_KEY                             | (generado)                                                            |
|                 | CLICKHOUSE_CLUSTER_ENABLED                 | false                                                                 |
|                 | Almacenamiento en Blob (S3)                |                                                                       |
|                 | LANGFUSE_S3_EVENT_UPLOAD_ENABLED           | true                                                                  |
|                 | LANGFUSE_S3_EVENT_UPLOAD_BUCKET            | (nombre del bucket)                                                   |
|                 | LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT          | http://minio.railway.internal:9000                                    |
|                 | LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE  | true                                                                  |
|                 | LANGFUSE_S3_EVENT_UPLOAD_PREFIX            | events/                                                               |
|                 | LANGFUSE_S3_EVENT_UPLOAD_REGION            | us-east-1                                                             |
|                 | LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID     | (clave de acceso)                                                     |
|                 | LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY | (secreto)                                                             |
|                 | LANGFUSE_ENABLE_EVENTS_TABLE_UI            | true (para usar events en la UI)                                      |
| langfuse-worker | (Mismas que langfuse-web)                  | —                                                                     |

### Notas de seguridad

-   Todas las contraseñas y secretos se gestionan mediante variables de entorno en Railway, no en código fuente.
-   Las DNS internas (`*.railway.internal`) garantizan que las comunicaciones entre servicios sean privadas y no expuestas a Internet.
-   Los puertos de las bases de datos no están expuestos públicamente, solo accesibles desde la red interna de Railway.

## ****Canales de Implementación y Consumo****  
  
### ****1. Frontend Web (Streamlit)****  
\- Permite interacción humana con el agente.  
\- Envía peticiones a \`/chat\` con \`fingerprint\` y \`thread\_id\`.  
\- Soporte para carga de imágenes (facturas) y audio (STT/TTS).  
  
### ****2. Automatización (n8n)****  
\- Integración mediante webhook \`/webhook/whatsapp\`.  
\- Payload esperado:  
  
\`\`\`json  
{  
  "number": "+50212345678",  
  "text": "Mensaje del cliente",  
  "datos\_cliente": { ... },  
  "chat\_id": "odoo\_chat\_id"  
}

-   Headers: `Authorization: Bearer API_KEY`, `Content-Type: application/json`.

### 3\. Depuración (cliente-debug)

-   Consola web para probar la API, ver respuestas en streaming y validar webhooks.
-   Permite cargar archivos multimedia para pruebas de visión y audio.
-   Tecnología: Flask 3.0.3 con Werkzeug 3.0.3 (compatible con Python 3.11).

### 4\. Observabilidad (Langfuse v3)

-   Dashboard web para visualizar trazas LLM, costos, latencias y errores.
-   Consultas analíticas sobre trazas históricas.
-   Evaluación de calidad mediante `scores` (feedback).

## Pruebas de Caja Negra y Validación Continua

| ID     | Prueba                          | Entrada                                            | Resultado Esperado                                                                                                                                                             | Estado                            |
| ------ | ------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| BC-T01 | Conversación On-Grid            | Mensaje: "Quiero paneles solares para ahorrar luz" | Clasificación correcta a On-Grid; selección de productos del bloque 1-10.                                                                                                      | ✅ Validado                        |
| BC-T02 | Conversación Off-Grid           | Mensaje: "Necesito sistema aislado para mi finca"  | Clasificación correcta a Off-Grid; selección de productos del bloque 19, 20, 23, etc.                                                                                          | ✅ Validado                        |
| BC-T03 | Extracción de nombre y WhatsApp | Mensaje: "Me llamo Juan, mi número es 12345678"    | Nombre: "Juan", WhatsApp: "+50212345678".                                                                                                                                      | ✅ Validado                        |
| BC-T04 | Fallo de Odoo                   | Odoo inaccesible                                   | El agente continúa funcionando con la ontología local; log de error en CTFOM.                                                                                                  | ✅ Validado                        |
| BC-T05 | Validación de schema            | Petición /chat sin thread_id                       | Error 422 (validación).                                                                                                                                                        | ✅ Validado                        |
| BC-T06 | OCR de factura                  | Imagen de factura EEGSA                            | Extracción de empresa_electrica, consumo_kwh, monto_factura.                                                                                                                   | ⏳ Pendiente                       |
| BC-T07 | Telemetría CTFOM activa         | Ejecución de nodo                                  | Evento registrado en telemetry_events con trace_id y span_id.                                                                                                                  | ✅ Validado                        |
| BC-T08 | Traza completa en Langfuse      | Ejecución de grafo                                 | Traza visible en Langfuse con user_id, session_id, metadata (objeto), public=false, bookmarked=false. (Requiere resincronización manual de la tabla events en caso de pérdida) | ✅ Validado (con Playbook)         |
| BC-T09 | Despacho verificado             | Envío de lead                                      | dispatch_events con ack_received=true.                                                                                                                                         | ✅ Validado                        |
| BC-T10 | Health check                    | Petición a /                                       | Respuesta 200 OK con estado del servicio.                                                                                                                                      | ✅ Validado                        |
| BC-T11 | Feedback de usuario             | POST a /feedback con trace_id y value              | Score registrado en Langfuse.                                                                                                                                                  | ✅ Validado                        |
| BC-T12 | Migración de bases de datos     | Ejecución de db_migrate_unificado.py               | Tablas creadas en CTFOM y BI sin errores.                                                                                                                                      | ✅ Validado                        |
| BC-T13 | Recuperación de tabla events    | Eliminación / vaciado de events                    | Recreación de la tabla y resincronización desde traces                                                                                                                         | ✅ Validado (Playbook documentado) |

## 🛠️ Playbook de Recuperación: Tabla `events`

En caso de que la UI de Langfuse muestre "No results" a pesar de tener datos en `traces`, ejecute el siguiente procedimiento en el contenedor de ClickHouse (`clickhouse-client`):

### 1\. Crear la tabla `events` (si no existe)

sql

CREATE TABLE IF NOT EXISTS default.events (  
    id String,  
    project\_id String,  
    trace\_id String,  
    name String,  
    type String,  
    timestamp DateTime64(3),  
    metadata String,  
    tags Array(String),  
    environment String,  
    user\_id String,  
    session\_id String,  
    version String,  
    observation\_id String,  
    parent\_observation\_id String,  
    start\_time DateTime64(3),  
    end\_time DateTime64(3),  
    level String,  
    status\_message String,  
    completion\_start\_time DateTime64(3),  
    model String,  
    model\_parameters String,  
    usage String,  
    input String,  
    output String,  
    latency String,  
    time\_to\_first\_token String,  
    input\_cost String,  
    output\_cost String,  
    total\_cost String,  
    prompt\_id String,  
    prompt\_name String,  
    prompt\_version String,  
    created\_at DateTime64(3)  
) ENGINE = MergeTree()  
ORDER BY (project\_id, timestamp)  
SETTINGS index\_granularity = 8192;

### 2\. Poblar `events` con trazas existentes

sql

INSERT INTO default.events (  
    id, project\_id, trace\_id, name, type, timestamp,  
    environment, user\_id, session\_id, created\_at  
)  
SELECT  
    id, project\_id, id AS trace\_id, name, 'trace' AS type, timestamp,  
    environment, user\_id, session\_id, created\_at  
FROM default.traces  
WHERE project\_id = 'cms3h8tt70006mk02zfdrv6h9';

### 3\. (Opcional) Poblar `events` con observaciones

sql

INSERT INTO default.events (  
    id, project\_id, trace\_id, name, type, timestamp,  
    environment, user\_id, session\_id, created\_at,  
    observation\_id, parent\_observation\_id, start\_time, end\_time,  
    level, status\_message, model, model\_parameters, usage,  
    input, output, latency, time\_to\_first\_token,  
    input\_cost, output\_cost, total\_cost,  
    prompt\_id, prompt\_name, prompt\_version  
)  
SELECT  
    id, project\_id, trace\_id, name, 'observation' AS type, start\_time AS timestamp,  
    environment, '' AS user\_id, '' AS session\_id, created\_at,  
    id AS observation\_id, parent\_observation\_id, start\_time, end\_time,  
    level, status\_message, provided\_model\_name AS model, model\_parameters,  
    toString(usage\_details) AS usage, input, output,  
    '' AS latency, '' AS time\_to\_first\_token, '' AS input\_cost, '' AS output\_cost,  
    total\_cost, prompt\_id, prompt\_name, prompt\_version  
FROM default.observations  
WHERE project\_id = 'cms3h8tt70006mk02zfdrv6h9';

### 4\. Habilitar la UI para usar `events`

En `langfuse-web` y `langfuse-worker`, asegurar que la variable esté configurada:

text

LANGFUSE\_ENABLE\_EVENTS\_TABLE\_UI=true

Luego reiniciar ambos servicios:

bash

railway restart langfuse-web  
railway restart langfuse-worker

### 5\. Verificar

sql

SELECT count() FROM default.events WHERE project\_id = 'cms3h8tt70006mk02zfdrv6h9';

El resultado debe ser la suma de trazas y observaciones (264 + 150 = 414 en el ejemplo).

## Gobernanza y Cumplimiento Normativo

| Estándar                  | Principio                                                               | Implementación                                                                     |
| ------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| ISO/IEC 25010 (Calidad)   | Mantenibilidad: código modular, documentado, con pruebas de caja negra. | Separación de módulos, docstrings, pruebas documentadas.                           |
|                           | Fiabilidad: reducción de puntos de fallo, aislamiento de servicios.     | Topología de microservicios con DNS dedicadas y bases de datos separadas.          |
|                           | Eficiencia: consultas analíticas no afectan la API transaccional.       | BI y CTFOM en bases de datos independientes.                                       |
| ISO/IEC 27001 (Seguridad) | Gestión de secretos: credenciales en variables de entorno.              | Sin credenciales en código; Railway inyecta secretos.                              |
|                           | Reducción de superficie de ataque: solo puertos necesarios expuestos.   | Bases de datos en red privada; API y debug con autenticación.                      |
| ISO/IEC 29119 (Pruebas)   | Pruebas de caja negra documentadas.                                     | Tabla de pruebas con entradas y resultados esperados.                              |
|                           | Trazabilidad de pruebas: cada prueba se puede repetir y verificar.      | Pruebas automatizadas en entorno de staging.                                       |
| DORA (Resiliencia)        | Separación de contextos: fallo en un distrito no afecta a los demás.    | Si Langfuse falla, el core sigue operativo; si BI falla, la API no se ve afectada. |
|                           | Registro de incidentes y trazabilidad de decisiones.                    | CTFOM y Langfuse registran eventos y errores.                                      |
|                           | Plan de recuperación documentado.                                       | Playbook de events y política de limpieza de checkpoints.                          |

## Stack Tecnológico y Dependencias (Versiones Exactas)

| Componente                    | Versión | Propósito                                              | Nota                        |
| ----------------------------- | ------- | ------------------------------------------------------ | --------------------------- |
| Python                        | 3.11    | Lenguaje base.                                         |                             |
| FastAPI                       | 0.115.0 | Framework de la API REST.                              |                             |
| Uvicorn                       | 0.30.1  | Servidor ASGI.                                         |                             |
| LangChain                     | 0.2.17  | Framework para agentes.                                |                             |
| LangChain Core                | 0.2.43  | Núcleo de LangChain.                                   |                             |
| LangChain Community           | 0.2.19  | Integraciones comunitarias.                            |                             |
| LangChain OpenAI              | 0.1.25  | Integración con OpenAI.                                |                             |
| LangGraph                     | 0.2.56  | Orquestación de grafos de estados.                     |                             |
| LangGraph Checkpoint Postgres | 2.0.7   | Persistencia de checkpoints en PostgreSQL.             |                             |
| OpenAI                        | 1.50.0  | Modelos LLM (GPT-4o-mini).                             |                             |
| Langfuse                      | 3.9.0   | Observabilidad LLM (SDK v3, usado vía adaptador REST). | Versión real en producción. |
| psycopg[binary]               | 3.3.4   | Driver PostgreSQL síncrono.                            |                             |
| SQLAlchemy                    | 2.0.31  | ORM para auditoría.                                    |                             |
| asyncpg                       | 0.29.0  | Driver asíncrono PostgreSQL.                           |                             |
| pydantic-settings             | 2.2.0   | Configuración tipada.                                  |                             |
| requests                      | 2.32.3  | Cliente HTTP.                                          |                             |
| beautifulsoup4                | 4.12.3  | Parseo HTML (extractor de precios).                    |                             |
| python-dotenv                 | 1.0.1   | Carga de variables de entorno.                         |                             |
| httpx                         | 0.27.2  | Cliente HTTP asíncrono.                                |                             |
| psutil                        | 5.9.8   | Monitoreo de recursos.                                 |                             |
| symspellpy                    | 6.7.0   | Corrección ortográfica.                                |                             |
| rapidfuzz                     | 3.0.0   | Fuzzy matching.                                        |                             |
| redis                         | 5.0.0   | Cliente Redis.                                         |                             |
| tiktoken                      | 0.7.0   | Tokenización para OpenAI.                              |                             |
| Flask                         | 3.0.3   | Framework para cliente-debug.                          |                             |
| Werkzeug                      | 3.0.3   | Servidor WSGI para Flask.                              |                             |

## Referencias Técnicas y Estándares (APA 8ª ed.)

-   Langfuse. (2026). __Ingestion API Reference__. Langfuse Documentation. [https://langfuse.com/docs/api/ingestion](https://langfuse.com/docs/api/ingestion)
-   Langfuse. (2026). __Self-hosting Langfuse v3__. Langfuse Documentation. [https://langfuse.com/docs/deployment/self-host](https://langfuse.com/docs/deployment/self-host)
-   LangChain. (2026). __LangGraph Documentation__. [https://langchain-ai.github.io/langgraph/](https://langchain-ai.github.io/langgraph/)
-   ISO/IEC. (2011). __ISO/IEC 25010:2011 - Systems and software engineering — System and software quality models.__
-   ISO/IEC. (2022). __ISO/IEC 27001:2022 - Information security, cybersecurity and privacy protection.__
-   ISO/IEC. (2022). __ISO/IEC 29119:2022 - Software and systems engineering — Software testing.__
-   European Union. (2022). __DORA (EU) 2022/2554 - Digital Operational Resilience Act.__

## Roadmap Estratégico

### Fase 1: Estabilización de Observabilidad (Completada)

-   ✅ Integración de Langfuse v3 con adaptador REST propio.
-   ✅ Separación de bases de datos CTFOM, BI y Langfuse.
-   ✅ Documentación del Playbook de recuperación de `events`.
-   ✅ Política de limpieza de checkpoints de LangGraph (pendiente de automatización).

### Fase 2: Migración a Langfuse v4 (Planificada)

-   🔲 Actualizar Langfuse a v4 y reemplazar el adaptador REST por el SDK nativo.
-   🔲 Implementar `propagate_attributes()` y `CallbackHandler` de v4.
-   🔲 Actualizar la documentación para reflejar la nueva instrumentación.

### Fase 3: Memoria Semántica (En curso)

-   ⏳ Implementación de `pgvector` para búsqueda semántica en PostgreSQL.
-   ⏳ Almacenamiento de embeddings de conversaciones para contextualización avanzada.

### Fase 4: Agentes Especialistas (Planificado)

-   🔲 Agente On-Grid.
-   🔲 Agente Off-Grid.
-   🔲 Agente de Bombeo Solar.
-   🔲 Agente de Solar Térmico.

### Fase 5: Predictive Bottleneck Engine (Planificado)

-   🔲 Modelo ML para predecir cuellos de botella en la conversación.
-   🔲 Autoajuste de prompts basado en telemetría operacional.

### Fase 6: Reflexive Truth Engine (Planificado)

-   🔲 Sistema de autoajuste de prompts basado en evaluación de calidad y costos.

## Licencia y Propiedad Intelectual

Este software es propiedad de AISA Solar y está sujeto a acuerdos de confidencialidad. Su uso, reproducción o distribución sin autorización expresa está prohibido.

Todos los derechos reservados © 2025-2026 AISA Solar.

__Documento generado para auditoría técnica y gobernanza de software.__  
__Última actualización: 03 de agosto de 2026.__  
__Versión Auditada: 2.0.19__

## 📌 Resumen Ejecutivo para el Comité de Evaluación Técnica

-   El sistema está en producción activa en Railway con todos los servicios funcionando.
-   La trazabilidad LLM en Langfuse v3 está operativa mediante un adaptador REST propio (`LangfuseIngestionAdapter`), no mediante SDK nativo.
-   Se ha documentado un Playbook de recuperación para la tabla `events` en caso de pérdida de visibilidad en la UI.
-   Se han identificado y corregido discrepancias entre la documentación y la realidad operacional.
-   El sistema cumple con los estándares ISO/IEC 25010, 27001, 29119 y DORA, siempre que se sigan los procedimientos documentados (incluyendo limpieza periódica de checkpoints y backups de ClickHouse).
-   El código fuente está disponible en el repositorio GitHub para auditoría.


