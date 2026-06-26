JARVI 2.0.02– Agente de Preventa para AISA Solar


 JARVI 2.0.02 – Agente de Preventa Técnica para AISA Solar

 Arquitectura de Agente Cognitivo con Persistencia de Estado Seriable, Orquestación de Grafo Determinista y Gobernanza Forense de Eventos Auditables

---

 Tabla de Contenidos

1. Resumen Ejecutivo
2. Evolución Arquitectónica: Hacia la Consistencia Distribuida
3. Arquitectura en Producción
 Componentes de Control y Concurrencia
 Gestión de Base de Conocimiento Híbrida
 Motor Cognitivo: Grafo de Estados Determinista
 Trazabilidad, Auditoría Forense y Observabilidad
 Despliegue e Infraestructura Serverless


4. Análisis Ontológico y Epistemológico del Desacoplamiento
5. Referencias Técnicas (APA 8)
6. Conclusión y Roadmap de Evolución

---

 1. Resumen Ejecutivo

JARVI 2.0.02 es el agente de inteligencia artificial de AISA Solar diseñado para la preventa técnica de sistemas fotovoltaicos. Esta versión marca un hito en la madurez técnica del proyecto, transicionando de un modelo de chatbot reactivo a un motor de razonamiento agéntico de alta disponibilidad con persistencia distribuida. Su misión es diagnosticar necesidades energéticas, recomendar equipos del catálogo institucional y generar oportunidades comerciales bajo estrictos estándares de trazabilidad, auditabilidad ACID (Atomicidad, Consistencia, Aislamiento, Durabilidad) y gobernanza técnica.

La solución cumple con las normativas ISO/IEC 42001 (Sistemas de IA) e ISO/IEC 27001 (Seguridad de la Información), empleando un diseño de arquitectura limpia que desacopla la capa de transporte (API), la capa de razonamiento (Grafo) y la capa de persistencia (Base de Datos). Este despliegue garantiza que cada interacción sea auditable, determinista y escalable, eliminando el riesgo de corrupción de estados en entornos concurrentes y mitigando las alucinaciones mediante una base de conocimiento híbrida Odoo-Scraping altamente verificada.

---

 2. Evolución Arquitectónica: Hacia la Consistencia Distribuida

La primera versión de JARVI operaba bajo una estructura monolítica, donde la interfaz y la lógica cognitiva compartían un mismo espacio de ejecución volátil. Esto generaba riesgos de degradación en el rendimiento y pérdida de contexto ante micro-cortes en el servicio. La versión 2.0.02 responde a la necesidad de profesionalización técnica mediante una refactorización basada en principios de arquitectura distribuida.

La evolución técnica se centra en cuatro pilares:

1. Desacoplamiento de Ciclo de Vida: Se ha implementado un `lifespan` asíncrono que inicializa el motor de persistencia (`AsyncPostgresSaver`) antes de cualquier interacción, evitando la latencia de inicialización en tiempo de ejecución.
2. Atomicidad de Estado: El estado del agente ya no reside en memoria volátil de forma aislada, sino que se sincroniza continuamente con PostgreSQL.
3. Gestión de Concurrencia: Se introdujo una "válvula de seguridad" mediante exclusión mutua, permitiendo que el sistema escale sin temor a colisiones de datos.
4. Separación de Responsabilidades (SRP): Cada módulo adquiere una identidad funcional única, facilitando auditorías de código independientes para cada dominio del sistema.

| Módulo | Responsabilidad Técnica |
| --- | --- |
| `api.py` | Orquestación RESTful, validación de concurrencia y gestión de tareas de fondo. |
| `agent_graph.py` | Definición del grafo de razonamiento, estados y puntos de control. |
| `audit.py` | Implementación de trazabilidad forense 360° y notificación de incidentes. |
| `odoo_client.py` | Interfaz XML-RPC para consulta de activos energéticos en tiempo real. |
| `ontology.py` | Normalización semántica y enriquecimiento de conceptos solares. |
| `schemas.py` | Contratos de datos (Pydantic) para asegurar la integridad de la entrada/salida. |

---

 3. Arquitectura en Producción

 Componentes de Control y Concurrencia

La capa de servicio (FastAPI) utiliza una arquitectura de "Válvula de Exclusión Mutua". Se emplea un `defaultdict(asyncio.Lock)` indexado por `thread_id`. Cuando el sistema recibe una petición desde n8n, el mutex "cierra la puerta" para ese hilo de conversación específico, obligando a las peticiones concurrentes a esperar en una cola determinista. Esto asegura que Jarvi nunca intente modificar el estado del grafo mientras otra inferencia está en curso, garantizando la consistencia ACID sobre el `AsyncPostgresSaver`.

 Base de Conocimiento Híbrida

El agente consulta Odoo 15 Community mediante XML-RPC para productos On-Grid, garantizando precios y disponibilidad en tiempo real. Para el resto de categorías, se emplea una ontología estática enriquecida con palabras clave validadas contra tesauros de ingeniería eléctrica. Esta combinación elimina la invención de datos comerciales, ya que el LLM funciona bajo un esquema de Recuperación Aumentada (RAG) estricta.

 Motor Cognitivo: Grafo de Estados Determinista

El grafo de estados define la secuencia: `Clasificador` → `Validador Geográfico` → `Chatbot` → `Tool Execution`. Cada nodo es un suceso atómico. El estado compartido `AgentState` se inyecta con el contexto técnico del usuario, permitiendo que el agente tome decisiones informadas sobre tarifas y normativas de distribuidoras locales en Guatemala.

 Trazabilidad, Auditoría Forense y Observabilidad

La arquitectura 2.0.02 implementa un mecanismo de "Auditoría Forense Asíncrona". Tras la respuesta al usuario, el sistema dispara una `BackgroundTask` que persiste el `run_id`, el `thread_id` y el estado final del grafo en una tabla de auditoría. Este proceso ocurre en un hilo independiente, evitando que la escritura en disco bloquee el retorno del mensaje, manteniendo la latencia de respuesta bajo niveles corporativos aceptables.

 Despliegue e Infraestructura Serverless

La aplicación se aloja en Railway bajo un paradigma serverless. Las variables de entorno son validadas por `config.py` al momento de la inicialización. Cualquier variable ausente provoca un `SystemExit` inmediato, evitando fallos silenciosos en producción.

---

 4. Análisis Ontológico y Epistemológico del Desacoplamiento

Desde la ontología de sistemas, esta refactorización corrige la falla de naturaleza del agente: su conocimiento ya no depende de la sesión de Streamlit, sino que se enraíza en una base de datos relacional persistente. Epistemológicamente, esto es una mejora fundamental: el "saber" del agente es ahora auditable. Un auditor externo puede verificar el estado histórico de cualquier consulta consultando el log de transacciones.

Al separar la lógica de transporte de la de razonamiento, garantizamos que el agente sea una entidad epistémica pura (el grafo) protegida por una coraza técnica (la API con sus locks y validaciones). Esta arquitectura protege al sistema de las contingencias del entorno (latencia, fallos de red) y asegura que el agente nunca base sus conclusiones en datos sin verificar. Es la materialización de la transparencia tecnológica exigida por las normas ISO.

---

 5. Referencias Técnicas (APA 8)

1. International Organization for Standardization. (2023). ISO/IEC 42001:2023 Information technology — Artificial intelligence — Management system.
2. LangChain Inc. (2025). LangGraph: Persistence and Multi-threading Guide.
3. PostgreSQL Development. (2025). Asynchronous Database Drivers and Connection Pooling.
4. FastAPI Documentation. (2025). Background Tasks and Concurrency Control.
5. Martin, R. C. (2017). Clean Architecture: A Craftsman's Guide.
6. Fielding, R. T. (2000). Architectural styles and the design of network-based software architectures.

---

 6. Conclusión y Roadmap de Evolución

JARVI 2.0.02 representa el estado del arte en preventa técnica solar. La arquitectura de concurrencia y persistencia aquí descrita permite que el sistema evolucione sin sacrificar su integridad fundamental. La robustez del diseño garantiza que el equipo de AISA Solar pueda escalar sus operaciones comerciales sabiendo que cada interacción con el cliente queda registrada bajo una auditoría forense completa.

Los próximos pasos en el roadmap incluyen la transición hacia una base de datos vectorial con `pgvector` para mejorar la recuperación semántica de catálogos complejos, manteniendo siempre este andamiaje de gobernanza y control. Jarvi no es solo un chat; es un sistema de ingeniería que documenta la verdad técnica en cada preventa, garantizando la confianza institucional en la era de la inteligencia artificial.
