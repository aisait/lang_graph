# JARVI 2.0.03 | Agente Cognitivo de Preventa Técnica para AISA Solar + OpenTelemetry + Langfuse v4.14.1

> Arquitectura de agente cognitivo con persistencia de estado serializable, orquestación mediante grafos deterministas, gobernanza forense de eventos auditables, canales de consumo desacoplados y telemetría cognitiva de grado industrial. Diseñado para operar en entornos de misión crítica con separación de contextos de datos, resiliencia operacional y trazabilidad completa bajo los estadares ISO.

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-green)
![LangGraph](https://img.shields.io/badge/LangGraph-agent-purple)
![Langfuse](https://img.shields.io/badge/Langfuse-observability-orange)
![ISO](https://img.shields.io/badge/ISO-25010%20%7C%2027001%20%7C%2029119-blue)
![CTFOM](https://img.shields.io/badge/CTFOM-telemetry-orange)
---

# Tabla de Contenidos

- [Resumen Ejecutivo](#resumen-ejecutivo)
- [Arquitectura Modular y Topología de Servicios](#arquitectura-modular-y-topología-de-servicios)
- [Telemetría Cognitiva CTFOM](#telemetría-cognitiva-ctfom)
- [Diseño de Base de Datos y Gobernanza de Datos](#diseño-de-base-de-datos-y-gobernanza-de-datos)
- [Arquitectura Lógica y Flujos de Información](#arquitectura-lógica-y-flujos-de-información)
- [Variables de Entorno por Servicio](#variables-de-entorno-por-servicio)
- [Canales de Implementación y Consumo](#canales-de-implementación-y-consumo)
- [Pruebas de Caja Negra y Validación Continua](#pruebas-de-caja-negra-y-validación-continua)
- [Gobernanza y Cumplimiento Normativo](#gobernanza-y-cumplimiento-normativo)
- [Stack Tecnológico y Dependencias](#stack-tecnológico-y-dependencias)
- [Referencias Técnicas y Estándares](#referencias-técnicas-y-estándares)
- [Roadmap Estratégico](#roadmap-estratégico)
- [Licencia y Propiedad Intelectual](#licencia-y-propiedad-intelectual)

---

# Resumen Ejecutivo

**JARVI 2.0.03** representa la evolución madura de la arquitectura agéntica de AISA Solar para la preventa técnica de soluciones fotovoltaicas. Esta versión incorpora el módulo **CTFOM (Cognitive Telemetry & Forensic Observability Middleware)** como capa de observabilidad cognitiva profunda, transformando el sistema en una plataforma de inteligencia operacional autoconsciente.

El sistema ha sido rediseñado topológicamente para operar en entornos de producción con tres distritos lógicos completamente aislados:

1. **Distrito Core (JARVI)**: Orquestación del agente conversacional, buffer de sesiones y auditoría de ejecución.
2. **Distrito de Observabilidad (Langfuse)**: Trazabilidad nativa de LLM, almacenamiento analítico de alto rendimiento y colas de procesamiento asíncrono.
3. **Distrito de Inteligencia (BI)**: Almacenamiento de datos de negocio estructurados (leads, resúmenes, hardware) para paneles de control y automatización (n8n).

La separación de contextos (Bounded Contexts) garantiza que las consultas analíticas pesadas no degraden la latencia de la API transaccional, y que los datos de observabilidad no interfieran con la auditoría forense de negocio. El sistema cumple con los estándares ISO/IEC 25010, 27001, 29119 y los principios de resiliencia operacional de DORA.

---

# Arquitectura Modular y Topología de Servicios

El sistema se despliega en Railway con una topología de microservicios con nombres unívocos y DNS internas dedicadas, eliminando cualquier colisión de responsabilidades.

| Servicio | Rol Ontológico | DNS Interna | Puerto | Dependencias Críticas |
|----------|----------------|-------------|--------|------------------------|
| `jarvi-backend` | Orquestador del agente (FastAPI + LangGraph) | `jarvi-backend.railway.internal` | 8080 | `redis-buffer`, `ctfom-postgres`, `bi-ia-postgres`, Langfuse (externo) |
| `cliente-debug` | Consola de depuración (Flask) | `cliente-debug.railway.internal` | 8081 | `jarvi-backend` (HTTP) |
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

# Telemetría Cognitiva CTFOM

El módulo CTFOM proporciona observabilidad profunda sin alterar el comportamiento funcional del agente. Opera en dos niveles:

1. **Telemetría de Infraestructura (CTFOM nativo)**:
   - Captura de eventos de ejecución del grafo con `trace_id`, `span_id`, latencia, CPU, memoria.
   - Registro de despachos a canales externos (webhooks, correos) con verificación de ACK.
   - Monitoreo de salud de servicios (`system_health`) y análisis de causa raíz (`root_cause_analysis`).
   - Persistencia en `ctfom-postgres` mediante worker asíncrono batch.

2. **Trazabilidad LLM (Langfuse)**:
   - Captura de prompts, respuestas, tokens y costos de cada llamada a OpenAI.
   - Visualización del flujo de ejecución del grafo en el dashboard de Langfuse.
   - Agrupación por usuario (`user_id` = número de WhatsApp en formato E.164) y sesión (`session_id` = `thread_id`).
   - Almacenamiento en `langfuse-clickhouse` para consultas analíticas de alto rendimiento.

**Coexistencia de CTFOM y Langfuse**:
- CTFOM se enfoca en la salud del sistema y auditoría de negocio.
- Langfuse se enfoca en la calidad de la respuesta del LLM y el análisis de costos.
- Ambos sistemas son complementarios y no comparten infraestructura de datos.

---

# Diseño de Base de Datos y Gobernanza de Datos

El esquema de bases de datos está completamente separado por contexto, siguiendo los principios de **Domain-Driven Design** y **segregación de responsabilidades**. Cada base de datos tiene un propósito único y no se superpone con las demás.

### 1. CTFOM Database (`ctfom-postgres`)

Contiene tablas de telemetría, auditoría y persistencia de estados del grafo:

- `telemetry_events`: eventos de ejecución (trace_id, span_id, latencia, CPU, memoria, metadata).
- `dispatch_events`: verificación de envíos a canales externos.
- `system_health`: estado de los servicios (heartbeat, latencia promedio, tasa de error).
- `root_cause_analysis`: análisis de fallos agregados.
- `checkpoints` y `checkpoint_blobs`: persistencia de estados de LangGraph.
- `audit_events`: auditoría de acciones de negocio (creación de oportunidades, etc.).

### 2. BI Database (`bi-ia-postgres`)

Almacena los datos de negocio estructurados que alimentan los paneles de inteligencia y la automatización:

- `threads`: información de clientes (`nombre_cliente`, `whatsapp_id`, `chat_id`, `fingerprint`, `metadata`).
- `resumenes`: resúmenes de conversaciones con metadatos de negocio (origen, fingerprint, etc.).

### 3. Langfuse Database (`langfuse-postgres`)

Gestionada por el propio Langfuse (Prisma). Contiene metadatos de usuarios, proyectos, API keys y configuración de la plataforma. No debe ser modificada por el código de JARVI.

### 4. ClickHouse (`langfuse-clickhouse`)

Almacena las trazas LLM (observaciones) en formato OLAP para consultas analíticas rápidas. Es el repositorio principal de la observabilidad de Langfuse.

**Política de migración**:
- Un único script (`db_migrate_unificado.py`) maneja la creación de tablas en ambas bases de datos (CTFOM y BI) utilizando variables de entorno `CTFOM_DATABASE_URL` y `BI_DATABASE_URL`.
- Las migraciones son idempotentes y se ejecutan en orden: primero CTFOM, luego BI.

---

# Arquitectura Lógica y Flujos de Información

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
        LangGraph -->|CallbackHandler| Langfuse[langfuse SDK]
        Langfuse --> LangfuseWeb[langfuse-web]
        Langfuse --> LangfuseWorker[langfuse-worker]
        LangfuseWorker --> ClickHouse[(langfuse-clickhouse)]
        LangfuseWorker --> RedisLangfuse[(redis-langfuse)]
        LangfuseWeb --> RedisLangfuse
    end

    subgraph BI[Inteligencia de Negocio]
        BI --> Metabase[bi-la-metabase]
        BI --> n8n
    end
```

**Flujo de información detallado**:

1. **Usuario → API**: El mensaje llega al endpoint `/chat` (frontend) o `/webhook/whatsapp` (n8n). La API extrae el `fingerprint` y el `chat_id`, y gestiona la sesión en `redis-buffer`.
2. **API → LangGraph**: La API invoca el grafo de LangGraph con el estado conversacional (`messages` y `contexto_tecnico`). El grafo ejecuta los nodos de clasificación, validación, selección de productos y generación de respuesta.
3. **LangGraph → CTFOM**: Cada nodo está decorado con `@observe_node`, que registra eventos en `telemetry.py`. El worker asíncrono inserta los eventos en `ctfom-postgres`.
4. **LangGraph → Langfuse**: El `CallbackHandler` de Langfuse captura cada ejecución del grafo (prompts, respuestas, tokens, costos) y los envía a `langfuse-web` y `langfuse-worker`. Las trazas se almacenan en `langfuse-clickhouse` y los metadatos en `langfuse-postgres`.
5. **API → BI**: Los resúmenes de conversaciones y los datos de los clientes se guardan en `bi-ia-postgres` (tablas `resumenes` y `threads`). Esta información es consumida por Metabase para dashboards de negocio y por n8n para automatización de leads.
6. **API → Redis**: El estado conversacional (sesión, historial) se almacena en `redis-buffer` con TTL de 7 días, permitiendo recuperar el contexto en conversaciones multi-turno.

**Observabilidad transversal**:
- **CTFOM**: Captura eventos de infraestructura y auditoría en `ctfom-postgres`.
- **Langfuse**: Captura trazas LLM en `langfuse-clickhouse`.
- **Ambos sistemas** utilizan el mismo `thread_id` y `user_id` para correlacionar eventos de negocio con trazas de LLM.

---

# Variables de Entorno por Servicio

La siguiente tabla detalla las variables de entorno necesarias para cada servicio en producción, alineadas con la topología actual.

| Servicio | Variables Clave | Valor / Referencia |
|----------|----------------|-------------------|
| **jarvi-backend** | `PORT` | `8080` |
| | `CHATBOT_MASTER_API_KEY` | `sk_...` |
| | `OPENAI_API_KEY` | `sk-...` |
| | `DATABASE_URL` (para checkpoints) | `postgresql://...` (puede apuntar a CTFOM) |
| | `CTFOM_DATABASE_URL` | `postgresql://...` (ctfom-postgres) |
| | `BI_DATABASE_URL` | `postgresql://...` (bi-ia-postgres) |
| | `REDIS_URL` | `redis://:${REDISPASSWORD}@redis-buffer.railway.internal:6379/0` |
| | `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` |
| | `LANGFUSE_SECRET_KEY` | `sk-lf-...` |
| | `LANGFUSE_HOST` | `https://langfuse-web-production-2599.up.railway.app` |
| | `LANGFUSE_TRACING_ENVIRONMENT` | `production` |
| | `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | (credenciales) |
| | `CONTROLLER_EMAIL` | `joseardon@aisa.com.gt` |
| | `ODOO_HOST`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` | (credenciales Odoo) |
| | `APICHAT_INSTANCE`, `APICHAT_ENDPOINT`, `APICHAT_TOKEN` | (webhook) |
| **cliente-debug** | `PORT` | `8081` |
| | `BACKEND_URL` | `https://jarvi-backend-production.up.railway.app` |
| | `CHATBOT_MASTER_API_KEY` | `sk_...` |
| **langfuse-web** | `DATABASE_URL` | (langfuse-postgres) |
| | `CLICKHOUSE_URL` | `http://langfuse-clickhouse.railway.internal:8123` |
| | `CLICKHOUSE_MIGRATION_URL` | `clickhouse://langfuse-clickhouse.railway.internal:9000` |
| | `REDIS_CONNECTION_STRING` | `redis://default:${REDISPASSWORD}@redis-langfuse.railway.internal:6379` |
| | `NEXTAUTH_URL` | `https://langfuse-web-production-2599.up.railway.app` |
| | `NEXTAUTH_SECRET` | (generado) |
| | `SALT` | (generado) |
| | `ENCRYPTION_KEY` | (generado) |
| | `CLICKHOUSE_CLUSTER_ENABLED` | `false` |
| **langfuse-worker** | (Mismas que `langfuse-web`) | — |
| **redis-buffer** | `REDISPASSWORD` | (autogenerado por Railway) |
| **redis-langfuse** | `REDISPASSWORD` | (autogenerado por Railway) |

**Notas de seguridad**:
- Todas las contraseñas y secretos se gestionan mediante variables de entorno en Railway, no en código fuente.
- Las DNS internas (`*.railway.internal`) garantizan que las comunicaciones entre servicios sean privadas y no expuestas a Internet.
- Los puertos de las bases de datos no están expuestos públicamente, solo accesibles desde la red interna de Railway.

---

# Canales de Implementación y Consumo

## 1. Frontend Web (Streamlit)
- Permite interacción humana con el agente.
- Envía peticiones a `/chat` con `fingerprint` y `thread_id`.
- Soporte para carga de imágenes (facturas) y audio (STT/TTS).

## 2. Automatización (n8n)
- Integración mediante webhook `/webhook/whatsapp`.
- Payload esperado:
  ```json
  {
    "number": "+50212345678",
    "text": "Mensaje del cliente",
    "datos_cliente": { ... },
    "chat_id": "odoo_chat_id"
  }
  ```
- Headers: `Authorization: Bearer API_KEY`, `Content-Type: application/json`.

## 3. Depuración (cliente-debug)
- Consola web para probar la API, ver respuestas en streaming y validar webhooks.
- Permite cargar archivos multimedia para pruebas de visión y audio.

## 4. Observabilidad (Langfuse)
- Dashboard web para visualizar trazas LLM, costos, latencias y errores.
- Consultas analíticas sobre trazas históricas.
- Evaluación de calidad mediante scores (feedback).

---

# Pruebas de Caja Negra y Validación Continua

Las siguientes pruebas de caja negra (ISO/IEC 29119) se ejecutan periódicamente para garantizar el correcto funcionamiento del sistema en producción:

| ID | Prueba | Entrada | Resultado Esperado |
|----|--------|---------|-------------------|
| **BC-T01** | Conversación On-Grid | Mensaje: "Quiero paneles solares para ahorrar luz" | Clasificación correcta a On-Grid; selección de productos del bloque 1-10. |
| **BC-T02** | Conversación Off-Grid | Mensaje: "Necesito sistema aislado para mi finca" | Clasificación correcta a Off-Grid; selección de productos del bloque 19, 20, 23, etc. |
| **BC-T03** | Extracción de nombre y WhatsApp | Mensaje: "Me llamo Juan, mi número es 12345678" | Nombre: "Juan", WhatsApp: "+50212345678". |
| **BC-T04** | Fallo de Odoo | Odoo inaccesible | El agente continúa funcionando con la ontología local; log de error en CTFOM. |
| **BC-T05** | Validación de schema | Petición `/chat` sin `thread_id` | Error 422 (validación). |
| **BC-T06** | OCR de factura | Imagen de factura EEGSA | Extracción de `empresa_electrica`, `consumo_kwh`, `monto_factura`. |
| **BC-T07** | Telemetría CTFOM activa | Ejecución de nodo | Evento registrado en `telemetry_events` con `trace_id` y `span_id`. |
| **BC-T08** | Traza completa en Langfuse | Ejecución de grafo | Traza visible en Langfuse con prompts, respuestas y costos. |
| **BC-T09** | Despacho verificado | Envío de lead | `dispatch_events` con `ack_received=true`. |
| **BC-T10** | Health check | Petición a `/` | Respuesta 200 OK con estado del servicio. |
| **BC-T11** | Feedback de usuario | POST a `/feedback` con `trace_id` y `value` | Score registrado en Langfuse. |
| **BC-T12** | Migración de bases de datos | Ejecución de `db_migrate_unificado.py` | Tablas creadas en CTFOM y BI sin errores. |

---

# Gobernanza y Cumplimiento Normativo

El sistema ha sido diseñado y auditado para cumplir con los siguientes estándares y regulaciones:

| Estándar | Principio | Implementación |
|----------|-----------|----------------|
| **ISO/IEC 25010** (Calidad del producto) | Mantenibilidad: código modular, documentado, con pruebas de caja negra. | Separación de módulos, docstrings, pruebas documentadas. |
| | Fiabilidad: reducción de puntos de fallo, aislamiento de servicios. | Topología de microservicios con DNS dedicadas y bases de datos separadas. |
| | Eficiencia: consultas analíticas no afectan la API transaccional. | BI y CTFOM en bases de datos independientes. |
| **ISO/IEC 27001** (Seguridad) | Gestión de secretos: credenciales en variables de entorno. | Sin credenciales en código; Railway inyecta secretos. |
| | Reducción de superficie de ataque: solo puertos necesarios expuestos. | Bases de datos en red privada; API y debug con autenticación. |
| **ISO/IEC 29119** (Pruebas) | Pruebas de caja negra documentadas. | Tabla de pruebas con entradas y resultados esperados. |
| | Trazabilidad de pruebas: cada prueba se puede repetir y verificar. | Pruebas automatizadas en entorno de staging. |
| **DORA** (Resiliencia operacional) | Separación de contextos: fallo en un distrito no afecta a los demás. | Si Langfuse falla, el core sigue operativo; si BI falla, la API no se ve afectada. |
| | Registro de incidentes y trazabilidad de decisiones. | CTFOM y Langfuse registran eventos y errores. |

---

# Stack Tecnológico y Dependencias

| Componente | Versión | Propósito |
|------------|---------|-----------|
| **Python** | 3.11 | Lenguaje base. |
| **FastAPI** | 0.115.0 | Framework de la API REST. |
| **Uvicorn** | 0.30.1 | Servidor ASGI. |
| **LangChain** | 0.2.17 | Framework para agentes. |
| **LangGraph** | 0.2.56 | Orquestación de grafos de estados. |
| **Langfuse** | >=2.0.0 | Observabilidad LLM. |
| **PostgreSQL** | 15+ | Bases de datos transaccionales (CTFOM, BI, Langfuse). |
| **ClickHouse** | 23.8+ | Almacenamiento OLAP para Langfuse. |
| **Redis** | 7.2+ | Cache de sesiones y colas. |
| **OpenAI** | 1.50.0 | Modelos LLM (GPT-4o-mini). |
| **Google API** | 2.198.0 | Envío de correos (Gmail). |
| **psutil** | 5.9.8 | Monitoreo de recursos. |
| **asyncpg** | 0.29.0 | Driver asíncrono PostgreSQL. |
| **SQLAlchemy** | 2.0.31 | ORM para auditoría. |
| **symspellpy** | 6.7.0 | Corrección ortográfica. |
| **rapidfuzz** | 3.0.0 | Fuzzy matching. |

---

# Referencias Técnicas y Estándares

- **ISO/IEC 25010:2011** — Systems and software engineering — System and software quality models.
- **ISO/IEC 27001:2022** — Information security, cybersecurity and privacy protection.
- **ISO/IEC 29119:2022** — Software and systems engineering — Software testing.
- **DORA (EU) 2022/2554** — Digital Operational Resilience Act.
- **LangGraph API Docs** — [https://langchain-ai.github.io/langgraph/](https://langchain-ai.github.io/langgraph/)
- **Langfuse Documentation** — [https://langfuse.com/docs](https://langfuse.com/docs)
- **OpenTelemetry Specification** — [https://opentelemetry.io/docs/specs/otel/](https://opentelemetry.io/docs/specs/otel/)
- **Google SRE Book** — [https://sre.google/](https://sre.google/)

---

# Roadmap Estratégico

## Fase 1: Madurez de Observabilidad (Completada)
- ✅ Integración de Langfuse como sistema de trazabilidad LLM.
- ✅ Separación de bases de datos CTFOM, BI y Langfuse.
- ✅ Eliminación del visualizador (LangGraph Studio) y consolidación en Langfuse.

## Fase 2: Memoria Semántica (En curso)
- ⏳ Implementación de `pgvector` para búsqueda semántica en PostgreSQL.
- ⏳ Almacenamiento de embeddings de conversaciones para contextualización avanzada.

## Fase 3: Agentes Especialistas (Planificado)
- 🔲 Agente On-Grid especializado en sistemas atados a la red.
- 🔲 Agente Off-Grid especializado en sistemas aislados.
- 🔲 Agente de Bombeo Solar.
- 🔲 Agente de Solar Térmico.

## Fase 4: Predictive Bottleneck Engine (Planificado)
- 🔲 Modelo ML para predecir cuellos de botella en la conversación.
- 🔲 Autoajuste de prompts basado en telemetría operacional.

## Fase 5: Reflexive Truth Engine (Planificado)
- 🔲 Sistema de autoajuste de prompts basado en evaluación de calidad y costos.

---

# Licencia y Propiedad Intelectual

Este software es propiedad de **AISA Solar** y está sujeto a acuerdos de confidencialidad. Su uso, reproducción o distribución sin autorización expresa está prohibido.

Todos los derechos reservados © 2025 AISA Solar.

---

**Documento generado para auditoría técnica y gobernanza de software. Última actualización: 17 de julio de 2026.**
