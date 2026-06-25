JARVI 2.0.01– Agente de Preventa para AISA Solar
Arquitectura Cognitiva Modular con Gobernanza Epistemológica para Sistemas Solares


Tabla de Contenidos
1. Resumen Ejecutivo
2. Evolución Arquitectónica: del Monolito al Desacoplamiento
3. Arquitectura en Producción
    - Vista general de componentes
    - Base de conocimiento híbrida: Odoo + Web Scraping
    - Ontología y enriquecimiento semántico
    - Motor cognitivo LangGraph
    - Gobernanza Humana (HITL) y herramientas
    - Trazabilidad y auditoría
    - Infraestructura serverless en Railway
4. Análisis Ontológico y Epistemológico del Desacoplamiento
5. Referencias Técnicas (APA 8)
6. Conclusión y Próximos Pasos


Resumen Ejecutivo

JARVI es el agente de inteligencia artificial conversacional de AISA Solar, especializado en la preventa técnica de sistemas solares. Su misión es diagnosticar necesidades energéticas, recomendar equipos del catálogo institucional y generar oportunidades comerciales con supervisión humana obligatoria, todo ello bajo estrictos criterios de trazabilidad, auditabilidad y gobernanza de datos.

La solución ha evolucionado desde un script monolítico en Streamlit hacia una arquitectura modular desacoplada, diseñada conforme a los principios de ISO/IEC 42001 (gestión de sistemas de IA) e ISO/IEC 27001 (seguridad de la información). La base de conocimiento se alimenta de dos fuentes complementarias: para los productos On‑Grid se consulta en tiempo real el ERP Odoo 15 Community mediante XML‑RPC, mientras que el resto de categorías utiliza una ontología enriquecida mediante web scraping controlado del sitemap oficial del sitio web corporativo. Este diseño híbrido garantiza la veracidad de los datos comerciales, elimina alucinaciones y permite la escalabilidad progresiva hacia una integración total con el ERP.

El presente documento describe la arquitectura actual en producción, los fundamentos de ingeniería de software que la sustentan y las decisiones epistemológicas que blindan al agente contra sesgos generativos, proporcionando una guía clara para que desarrolladores sénior y júnior puedan comprender, mantener y extender el sistema.


Evolución Arquitectónica: del Monolito al Desacoplamiento

La primera versión de JARVI residía íntegramente en un archivo main.py de aproximadamente 700 líneas, donde convivían la lógica de la interfaz gráfica (Streamlit), la definición de herramientas, la compilación del grafo de LangGraph, las conexiones a APIs externas, el decorador de auditoría y la ontología estática. Este modelo, aunque funcional, presentaba limitaciones estructurales:

- Alto acoplamiento: cualquier cambio en la configuración, la lógica de negocio o la base de conocimiento obligaba a modificar y redesplegar todo el monolito.
- Dificultad de testeo: no era posible probar componentes individuales sin simular el entorno completo de Streamlit.
- Latencia de re‑ejecución: Streamlit re‑ejecuta el script completo ante cada interacción del usuario; los imports masivos y las inicializaciones de clientes de red añadían microsegundos críticos que degradaban la experiencia.
- Riesgo de alucinaciones: la ontología estática, sin conexión a fuentes de verdad empresarial, podía quedar obsoleta si el catálogo cambiaba.

La refactorización aplicó los principios de separación de responsabilidades (SRP) y arquitectura limpia, dividiendo la aplicación en seis módulos con responsabilidades únicas:

| Módulo           | Responsabilidad principal                                      |
|------------------|-----------------------------------------------------------------|
| config.py        | Gobernanza de configuración y validación de entorno             |
| audit.py         | Trazabilidad, logging de auditoría y notificación de fallos     |
| odoo_client.py   | Abstracción de la capa de datos del ERP vía XML‑RPC              |
| ontology.py      | Gestión de la base de conocimiento híbrida y formateo para el LLM |
| agent_graph.py   | Orquestación del grafo conversacional y definición de herramientas |
| main.py          | Renderizado de la UI multimodal y punto de entrada serverless   |

Esta modularización no solo facilita el mantenimiento, sino que aísla las fuentes de datos y los mecanismos de supervisión, creando barreras de validación epistémica que impiden que la IA acceda a información no verificada.


Arquitectura en Producción

Vista general de componentes

El sistema se despliega en Railway bajo un paradigma serverless, con Streamlit como servidor web integrado. El flujo de una interacción típica sigue estos pasos:

1. El usuario ingresa un mensaje (texto, voz o imagen de factura) en la UI de Streamlit.
2. main.py captura el evento y lo encamina al grafo conversacional compilado en agent_graph.py.
3. El grafo ejecuta secuencialmente los nodos de clasificación topológica (detecta si la consulta es On‑Grid, Off‑Grid, Bombeo, etc.) y validación geográfica (asigna distribuidora y tarifa).
4. El nodo chatbot construye el prompt del sistema inyectando la ontología adecuada, recuperada mediante ontology.py.
5. El agente LLM (GPT‑4o mini) genera una respuesta y, si el usuario acepta la propuesta, invoca la herramienta procesar_oportunidad_backend, que envía asíncronamente los datos al Controller humano vía Gmail API y WhatsApp.
6. Todas las operaciones críticas están envueltas por el decorador auditar_fase de audit.py, que captura excepciones y notifica al equipo de ingeniería.

Base de conocimiento híbrida: Odoo + Web Scraping

La base de conocimiento se compone de dos fuentes complementarias:

- Productos On‑Grid (categorías 1‑10): se consultan en tiempo real al ERP Odoo 15 Community mediante XML‑RPC. Los campos name, description_sale, list_price, website_url y default_code se extraen y formatean para ser inyectados en el prompt del LLM. Un mecanismo de caché de 10 minutos (st.cache_data(ttl=600)) minimiza la latencia y la carga sobre el ERP.

- Resto de categorías (11‑86): se mantienen en una ontología estática enriquecida que es actualizada periódicamente mediante un proceso de web scraping del sitemap XML del sitio web de AISA. Los bloques incluyen nombre, URL de categoría y, en la versión avanzada, hasta 10 palabras clave por producto, organizadas en tres niveles de lenguaje (básico, pregrado, posgrado) para maximizar la recuperación semántica.

Esta arquitectura híbrida permite que el agente ofrezca datos precisos y actualizados para los productos de mayor demanda (On‑Grid), mientras mantiene una cobertura total del catálogo sin depender de conexiones ERP para categorías menos críticas.

Ontología y enriquecimiento semántico

El archivo ontology.py contiene la lógica de selección de fragmentos según la topología detectada. Para cada categoría, se define un bloque con:

- nombre: denominación comercial del producto.
- url: enlace directo al producto en el sitio web de AISA.
- keywords: un conjunto de 10 términos que simulan consultas de tres perfiles de usuario (básico, técnico medio, experto). Estas palabras clave mejoran la capacidad del LLM para empatar la intención del cliente con el producto correcto, incluso cuando el usuario emplea lenguaje coloquial.

El diseño de las keywords sigue una metodología académica ontológica: cada término fue validado contra tesauros de energía solar, normativas IEEE e IEC, y análisis de patrones de búsqueda de consumidores centroamericanos. Esto garantiza que el agente entienda desde “paneles solares para casa” hasta “módulo fotovoltaico monocristalino PERC half‑cut con certificación IEC 61215”.

Motor cognitivo LangGraph

El corazón del agente es un grafo de estados dirigido implementado con LangGraph. Cada nodo cumple una función específica y modifica el estado compartido (AgentState), que contiene tanto el historial de mensajes como el contexto_tecnico (topología, ciudad, tarifa, etc.).

El flujo es:
START → clasificador_topologia → validador_geolocalizacion → chatbot
                                                               ↓
                                                            tools
                                                               ↓
                                                            chatbot

El nodo chatbot recibe el estado actualizado y un prompt de sistema que incluye:
- Los datos firmados del contexto (ubicación, distribuidora, tarifa).
- Las reglas de conducción cognitiva aprobadas por la junta directiva (exención de responsabilidad, exclusividad de inventario).
- El fragmento de ontología correspondiente.

El LLM genera una respuesta y, si decide llamar a la herramienta procesar_oportunidad_backend, el grafo enruta al nodo tools y luego regresa al chatbot para el mensaje de cierre.

Gobernanza Humana (HITL) y herramientas

La herramienta procesar_oportunidad_backend es el punto de supervisión humana obligatoria. El agente nunca realiza transacciones automáticamente. En su lugar, envía un correo electrónico y un mensaje de WhatsApp al Controller humano con todos los datos de la oportunidad, incluyendo los equipos seleccionados y los enlaces de validación.

Esta herramienta opera en un hilo secundario (threading.Thread), por lo que no bloquea la interfaz del usuario. El envío se realiza mediante Gmail API (con OAuth2) y la API de AcruxLab para WhatsApp.

Trazabilidad y auditoría

El módulo audit.py implementa dos mecanismos clave:

1. Decorador auditar_fase: envuelve cada nodo del grafo y las funciones críticas, capturando excepciones, mostrando detalles en la UI (solo en desarrollo) y relanzando la excepción para que LangGraph maneje el estado correctamente.
2. Función notificar_error_runtime: ante fallos no controlados, envía asíncronamente un correo al Controller con el traceback completo, el prompt que falló y el estado de la sesión, garantizando el cumplimiento de los Acuerdos de Nivel de Servicio (ANS) e ITIL.

Todos los eventos significativos son registrados, permitiendo una trazabilidad completa de cada interacción, desde la consulta inicial hasta el envío del lead.

Infraestructura serverless en Railway

La aplicación se despliega en Railway, que proporciona:
- Variables de entorno seguras para todas las credenciales.
- Escalado automático.
- Bajo mantenimiento operativo.

La configuración se gestiona en config.py, que valida la existencia de todas las variables críticas al arranque, evitando fallos silenciosos en producción.


Análisis Ontológico y Epistemológico del Desacoplamiento

Desde la filosofía de la ingeniería de software, la refactorización responde a una necesidad de separación ontológica entre el ser del agente (su lógica de razonamiento) y los fenómenos que percibe (interfaz de usuario, datos del ERP, auditoría).

- Perspectiva Ontológica: en el monolito, las entidades de infraestructura, el estado cognitivo y las fuentes de verdad empresarial coexistían en un mismo plano, generando un acoplamiento que dificultaba la evolución. Al separarlas en módulos, cada elemento adquiere un ciclo de vida independiente y un único propósito.

- Perspectiva Epistemológica: la pregunta “¿cómo sabe el agente lo que sabe?” se responde con barreras de validación explícitas. La información proveniente de Odoo pasa por odoo_client.py, que abstrae la conexión y maneja los nulos sin error, y luego ontology.py la formatea. El LLM nunca recibe datos crudos sin filtrar, lo que blinda contra alucinaciones y cumple con los requisitos de transparencia de ISO 42001.

- Optimización de Latencia: al cachear la conexión a Odoo (@st.cache_resource) y los productos (@st.cache_data), la UI solo ejecuta el paso de inferencia, reduciendo el tiempo de respuesta y evitando que cada interacción del usuario dispare una nueva autenticación XML‑RPC.

Este diseño demuestra que es posible integrar IA generativa en procesos empresariales críticos sin renunciar a la gobernanza, la verificabilidad y el control humano.


Referencias Técnicas (APA 8)

1. International Organization for Standardization. (2023). ISO/IEC 42001:2023 Information technology — Artificial intelligence — Management system. ISO.
   Justificación: Define el marco de gestión de sistemas de IA adoptado para gobernar el ciclo de vida del agente, asegurando transparencia, responsabilidad y mejora continua.

2. International Organization for Standardization. (2022). ISO/IEC 27001:2022 Information security, cybersecurity and privacy protection — Information security management systems — Requirements. ISO.
   Justificación: Proporciona los controles de seguridad implementados en la gestión de secretos, variables de entorno y comunicaciones cifradas del sistema.

3. National Institute of Standards and Technology. (2023). Artificial Intelligence Risk Management Framework (AI RMF 1.0). NIST.
   Justificación: Los principios de mapeo, medición, gestión y gobierno de riesgos de IA guían la supervisión humana, la validación de salidas y la mitigación de alucinaciones del agente.

4. Fielding, R. T. (2000). Architectural styles and the design of network-based software architectures (Doctoral dissertation, University of California, Irvine).
   Justificación: El estilo REST y la separación de responsabilidades inspiran la arquitectura modular y la comunicación con el ERP vía XML‑RPC.

5. Richardson, C. (2018). Microservices patterns: With examples in Java. Manning Publications.
   Justificación: Aunque JARVI no es estrictamente un sistema de microservicios, los patrones de descomposición por dominio de negocio (contextos acotados) se aplicaron para aislar la lógica de Odoo, la ontología y la auditoría.

6. LangChain Inc. (2024). LangGraph documentation.
   Justificación: LangGraph es el orquestador de estados que permite definir el flujo conversacional como un grafo dirigido, con memoria y puntos de control, fundamental para la arquitectura cognitiva del agente.

7. OpenAI. (2024). Embeddings guide and API documentation.
   Justificación: Aunque el sistema actual no utiliza embeddings en producción, la fase de enriquecimiento semántico de la ontología se apoya en conceptos de representación vectorial para futuras iteraciones de búsqueda semántica.

8. PostgreSQL Global Development Group. (2024). PostgreSQL documentation.
   Justificación: La hoja de ruta contempla migrar la ontología a una base de datos vectorial con pgvector; esta referencia documenta la base tecnológica para dicha evolución.


Conclusión y Próximos Pasos

La arquitectura actual de JARVI representa un equilibrio pragmático entre la necesidad de datos comerciales precisos (Odoo para On‑Grid) y la cobertura total del catálogo (scraping para el resto). Su diseño modular, con validación de configuración, auditoría en tiempo real, y supervisión humana obligatoria, cumple con los estándares corporativos y normativos exigidos por la junta directiva y los auditores ISO.

El siguiente paso evolutivo será la completa integración con el ERP, eliminando el scraping residual y centralizando toda la ontología en Odoo, con persistencia en una base vectorial para recuperación semántica de alto rendimiento. Mientras tanto, cualquier desarrollador puede incorporarse al proyecto comprendiendo que:

- config.py es la puerta de entrada a la configuración segura.
- audit.py es el guardián de la trazabilidad.
- odoo_client.py es el traductor con el ERP.
- ontology.py es la memoria institucional viva.
- agent_graph.py es el cerebro conversacional.
- main.py es la piel que el usuario ve.

Esta claridad permite que un ingeniero sénior audite el cumplimiento normativo, mientras que un júnior puede modificar la ontología sin riesgo de romper la lógica de negocio. JARVI es, en esencia, un modelo de cómo la inteligencia artificial puede ser puesta al servicio de la ingeniería sin renunciar a la responsabilidad humana.****
