JARVI 2.0.02 – Agente de Preventa Técnica para AISA Solar
Arquitectura de Agente Cognitivo con Persistencia de Estado Seriable, Orquestación de Grafo Determinista y Gobernanza Forense de Eventos Auditables

graph TD
    S[Streamlit UI] -->|HTTP/SSE| API
    L[LangSmith] -->|HTTP| API
    N[n8n] -->|Webhook| API
    API -->|Graph| AGENT[Grafo LangGraph]
    AGENT -->|Tool Call| Odoo
    AGENT -->|Read| Ontologia(JSON Catálogo)
    AGENT -->|Persist| DB[(PostgreSQL)]
    API -->|Whisper/TTS| OpenAI
    API -->|Vision| OpenAI
    API -->|Audit| AuditLogger
    AuditLogger -->|Gmail API| Controller
---

 Tabla de Contenidos

1. Resumen Ejecutivo
2. Evolución Arquitectónica: Estructura Modular y Desacoplamiento
3. Arquitectura en Producción
 Orquestación y Concurrencia (FastAPI/Lifespan)
 Persistencia Distribuida (AsyncPostgresSaver)
 Grafo de Estados (LangGraph)
 Auditoría Asíncrona (BackgroundTasks)


4. Análisis Ontológico y Epistemológico
5. Referencias Técnicas (APA 8)
6. Conclusión y Roadmap

---

 1. Resumen Ejecutivo

JARVI 2.0.02 es la arquitectura de razonamiento agéntico de AISA Solar para la preventa técnica fotovoltaica. El sistema implementa un motor de grafos dirigidos con persistencias ACID en PostgreSQL, diseñado para entornos de alta concurrencia. A diferencia de las versiones previas, esta arquitectura garantiza la integridad de la sesión mediante un modelo de bloqueo serializado, cumpliendo estrictamente con los marcos de gobernanza de IA (ISO/IEC 42001) y seguridad de la información (ISO/IEC 27001).

 2. Evolución Arquitectónica

La transición del monolito (`main.py`) a la estructura actual en `/app` permite una separación clara de responsabilidades bajo los principios de Clean Architecture. La nueva disposición jerárquica es:

| Directorio | Propósito Técnico |
| --- | --- |
| `/app/api/` | Endpoints de entrada, gestión de `lifespan` y contratos de validación (Pydantic). |
| `/app/core/` | Lógica de negocio, configuración de variables de entorno y validadores. |
| `/app/database/` | Gestión de pool de conexiones y persistencia mediante `AsyncPostgresSaver`. |
| `/app/services/` | Abstracción de clientes externos (Odoo XML-RPC, WhatsApp, Gmail). |
| `/app/graph/` | Definición de nodos, bordes y estado compartido (`AgentState`). |
| `/app/utils/` | Decoradores de auditoría y utilidades de registro forense (`audit.py`). |

 3. Arquitectura en Producción

 Orquestación y Concurrencia

La capa de API implementa una válvula de seguridad utilizando `asyncio.Lock` en un `defaultdict`. Al asociar cada Lock a un `thread_id`, se garantiza que, aunque el sistema sea serverless y asíncrono, nunca existan operaciones de escritura concurrentes sobre el mismo checkpoint en la base de datos. El `lifespan` de FastAPI asegura que el grafo sea compilado una sola vez al inicio, optimizando los recursos de cómputo.

 Persistencia Distribuida

El sistema utiliza `PostgresSaver` para externalizar la memoria del agente. Esto resuelve la volatilidad de los contenedores efímeros: cada transición del grafo (`StateUpdate`) es un commit atómico en Postgres. Si el servicio de Railway se reinicia, el agente retoma exactamente desde el último nodo ejecutado, recuperando el contexto técnico (distribuidora, tarifa) sin fricción.

 Grafo de Estados (LangGraph)

El motor de razonamiento se define en `graph/agent.py`. La arquitectura separa los nodos de "razonamiento" (LLM) de los nodos de "acción" (Tools). Esta separación permite que el auditor examine los logs de ejecución de LangSmith para validar si las herramientas fueron invocadas bajo los parámetros correctos o si existió una desviación en la lógica de preventa.

 Auditoría Asíncrona

La integración del decorador `auditar_fase` en conjunto con `BackgroundTasks` permite el registro de telemetría sin incrementar el Time-to-First-Token (TTFT). Mientras el usuario recibe su respuesta, el sistema escribe en `audit_logs` la traza completa de la ejecución, permitiendo una trazabilidad total exigida por el Comité de Auditoría.

 4. Análisis Ontológico y Epistemológico

Ontológicamente, JARVI ha pasado de ser un "script que responde" a una "máquina de estado persistente". La distinción entre el estado del grafo (persistido en tablas relacionales) y el estado del chat (historial en memoria de corto plazo) es la barrera que garantiza la veracidad técnica.

Epistemológicamente, el sistema soluciona el problema de la "memoria fragmentada". Al delegar la verdad institucional a Odoo y la verdad lógica al Grafo, el agente no "cree" información, sino que "consulta" estados. Cualquier alucinación es ahora un fallo auditable que puede ser rastreado mediante el `run_id` y corregido mediante la inyección de metadatos más estrictos en el `AgentState`.

 5. Referencias Técnicas (APA 8)

1. International Organization for Standardization. (2023). ISO/IEC 42001:2023 Management system.
2. LangChain Inc. (2025). LangGraph: Persistence and Multi-threading Guide.
3. PostgreSQL Development. (2025). Asynchronous Database Drivers.
4. FastAPI Documentation. (2025). Background Tasks and Concurrency Control.
5. Martin, R. C. (2017). Clean Architecture.

 6. Conclusión y Roadmap

JARVI 2.0.02 es una arquitectura diseñada para la escalabilidad. La transición a esta estructura modular permite que el equipo de desarrollo extienda el sistema (añadiendo nuevos nodos al grafo) sin alterar la capa de transporte o la persistencia. El siguiente paso evolutivo es la centralización total de la ontología en el ERP y la implementación de una capa de memoria semántica mediante `pgvector`, consolidando a JARVI como la herramienta de preventa más auditable y robusta del sector solar.
