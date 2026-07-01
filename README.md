# JARVI 2.0.03 – Agente Cognitivo de Preventa Técnica para AISA Solar

**Arquitectura de Agente Cognitivo con Persistencia de Estado Serializable, Orquestación de Grafo Determinista, Gobernanza Forense de Eventos Auditables y Canales de Consumo Desacoplados.**

---

## Tabla de Contenidos

1.  [Resumen Ejecutivo](#1-resumen-ejecutivo)
2.  [Arquitectura Modular y Funcionalidad de Archivos (Enfoque Caja Negra)](#2-arquitectura-modular-y-funcionalidad-de-archivos-enfoque-caja-negra)
3.  [Variables de Entorno y Configuración en Railway](#3-variables-de-entorno-y-configuración-en-railway)
4.  [Métodos de Implementación por Canal de Consumo](#4-métodos-de-implementación-por-canal-de-consumo)
    -   [4.1 Canal Web Humano (Streamlit)](#41-canal-web-humano-streamlit)
    -   [4.2 Canal de Automatización (n8n)](#42-canal-de-automatización-n8n)
    -   [4.3 Canal de Evaluación y Trazabilidad (LangSmith)](#43-canal-de-evaluación-y-trazabilidad-langsmith)
5.  [Pruebas Integrales de Caja Negra (ISO/IEC 29119)](#5-pruebas-integrales-de-caja-negra-isoiec-29119)
6.  [Análisis Ontológico y Epistemológico del Sistema](#6-análisis-ontológico-y-epistemológico-del-sistema)
7.  [Referencias Técnicas (APA 8ª ed.)](#7-referencias-técnicas-apa-8ª-ed)
8.  [Conclusión y Roadmap](#8-conclusión-y-roadmap)

---

## 1. Resumen Ejecutivo

**JARVI 2.0.03** es la evolución de la arquitectura de razonamiento agéntico de AISA Solar, diseñada para la preventa técnica fotovoltaica. El sistema se ha refactorizado completamente para independizar los canales de consumo (Web Humano, n8n y LangSmith) de la lógica de negocio, centralizando toda la inteligencia, validación ontológica y auditoría en un servidor API único.

El núcleo del sistema es un motor de grafos dirigidos (LangGraph) con persistencia ACID en PostgreSQL. Esta versión garantiza que cualquier interfaz (un chat web, un flujo automatizado en n8n o un entorno de pruebas en LangSmith) ejecute exactamente la misma lógica de preventa, eliminando silos de información y cuellos de botella. El diseño desacoplado permite una escalabilidad horizontal y un tiempo de ejecución mínimo en plataformas serverless como Railway.

Esta guía está estructurada para que un profesional con conocimientos básicos de tecnología pueda comprender, desplegar y validar la solución, apoyándose en los estándares internacionales de calidad (ISO/IEC 25010), documentación (ISO/IEC 26514), pruebas (ISO/IEC 29119) y gobernanza de IA (ISO/IEC 42001).

## 2. Arquitectura Modular y Funcionalidad de Archivos (Enfoque Caja Negra)

A continuación se describe la función de cada componente del sistema como una "caja negra", detallando qué hace y cómo se puede probar sin necesidad de inspeccionar el código interno.

| Archivo / Componente | Función Principal | Prueba de Caja Negra Sugerida (¿Cómo verifico que funciona?) |
| :--- | :--- | :--- |
| `api.py` | **Servidor Central de Lógica de Negocio.** Es el único punto de entrada para todas las operaciones inteligentes. Recibe mensajes, coordina el grafo de IA, aplica reglas de negocio y devuelve respuestas. | Enviar una petición HTTP POST a su dirección (ej. `/chat`) con un JSON de prueba. Debe devolver una respuesta del agente o un stream de tokens. |
| `agent_graph.py` | **El Cerebro del Agente.** Define la máquina de estados que modela una conversación de preventa. Contiene los nodos que clasifican la necesidad (ej. si es un sistema solar aislado o conectado a la red), validan la ubicación y generan la respuesta con el LLM. | Inyectar un mensaje como "Quiero un sistema para mi finca sin electricidad". El estado del grafo debe reflejar `topologia = "Off-Grid"`. La respuesta final debe incluir enlaces a kits aislados. |
| `streamlit_app.py` | **Interfaz de Usuario Web (Canal Humano).** Es una "cáscara ligera" que pinta la conversación. No tiene inteligencia propia; envía todo el input (texto, voz, imágenes) a la API central y muestra la respuesta. | Abrir la URL pública en un navegador. Escribir un mensaje y verificar que la respuesta del asistente aparece token por token. Grabar un mensaje de voz y ver que se transcribe y se responde. |
| `ontology.py` | **Módulo de Ruteo Epistemológico.** Carga el catálogo de productos y selecciona el fragmento relevante según la topología detectada. Esto le da al agente el "conocimiento" necesario sin saturarlo con todo el catálogo. | Preguntar al agente por un "sistema conectado a la red". Las respuestas deben incluir enlaces a productos On-Grid. Preguntar por "bombas de agua solares" y verificar que los enlaces son de la categoría de bombeo. |
| `catalog_ontology.json` | **Fuente de Verdad Referencial.** Contiene las 86 categorías de productos de AISA Solar, con sus nombres, URLs y palabras clave. Es leído por `ontology.py`. | Abrir el archivo y verificar que la URL `https://www.aisa.com.gt/shop/category/sistemas-atados-a-la-red-7` carga correctamente en un navegador. |
| `odoo_client.py` | **Conector al ERP Odoo.** Se comunica con el sistema de inventario y precios para obtener datos maestros de productos. La API central lo utiliza para enriquecer las respuestas con información de Odoo. | Realizar una consulta a la API que requiera datos de Odoo (si está implementado el endpoint). Verificar que la API no se bloquea si Odoo no está disponible (debe fallar con gracia). |
| `audit.py` | **Sistema de Auditoría y Alerta.** Envuelve funciones críticas para registrar automáticamente cualquier fallo (trazas, argumentos) y notifica al equipo de ingeniería por correo electrónico si ocurre un error grave. | Provocar un error en la API (ej. enviando datos incorrectos). Verificar que en los logs de Railway aparece un mensaje de error con el prefijo `[AUDITORÍA]`. Si el error es muy grave, el Controller recibirá un correo. |
| `config.py` | **Centro de Configuración.** Lee todas las variables de entorno de Railway (API keys, URLs) y las valida al iniciar. Asegura que el backend no arranque sin las credenciales mínimas. | Iniciar la API sin la variable `OPENAI_API_KEY`. El servicio debe fallar inmediatamente con un mensaje claro de "Falla de Seguridad ISO 27001". |
| `db_migrate.py` | **Herramienta de Preparación de Base de Datos.** Crea las tablas necesarias en PostgreSQL para guardar el estado de las conversaciones y los eventos de auditoría. | Ejecutar el script manualmente o ver los logs de la API al desplegar. Debe aparecer el mensaje "Migración completada exitosamente". Conectarse a la base de datos y verificar que las tablas `checkpoints` y `audit_events` existen. |
| `schemas.py` | **Contratos de Datos (Validación).** Define la estructura exacta que deben tener los mensajes de entrada y salida de la API. Garantiza que todos los canales "hablen el mismo idioma". | Enviar una petición a la API con un JSON que no tenga el campo `message`. La API debe rechazarla con un error 422 "Unprocessable Entity". |
| `vision.py` | **Servicio de Visión Artificial.** Procesa imágenes de facturas de electricidad y extrae el nombre de la empresa, el consumo y el monto. Solo se activa bajo demanda. | Usar la interfaz web para subir una foto de una factura real. La API debe responder con los datos extraídos. Subir una foto de un paisaje; los campos deben devolverse en blanco o nulos. |
| `Dockerfile.api` | **Receta de Empaquetado del Backend.** Define cómo se construye el contenedor de la API para que se ejecute en Railway. | Desplegarlo en Railway. El servicio `cliente-api` debe arrancar y mostrar logs de Uvicorn sin errores de importación. |
| `Dockerfile.streamlit` | **Receta de Empaquetado de la Interfaz Web.** Define cómo se construye el contenedor de la UI. | Desplegarlo en Railway. El servicio `cliente-humano` debe arrancar y ser accesible desde un navegador. |
| `langgraph.json` | **Punto de Entrada para LangGraph.** Define los grafos disponibles. Permite a LangSmith o herramientas de desarrollo conectar directamente con el cerebro del agente. | Ejecutar `langgraph dev` en un entorno local. La interfaz de LangGraph Studio debe cargar y permitir ejecutar el grafo `aisa_chatbot`. |

## 3. Variables de Entorno y Configuración en Railway

JARVI 2.0.03 se despliega en dos servicios de Railway que comparten una base de datos PostgreSQL. Es crucial que las variables de entorno estén correctamente asignadas.

**Servicio: `cliente-api` (Backend)**
*Contiene el archivo `api.py`.*
Requiere todas las credenciales para operar.

| Variable de Entorno | Descripción y Propósito |
| :--- | :--- |
| `CHATBOT_MASTER_API_KEY` | La "contraseña" que deben usar todos los clientes (UI, n8n) para hablar con la API. |
| `OPENAI_API_KEY` | Clave para usar los modelos de OpenAI (GPT, Whisper, TTS). |
| `DATABASE_URL` | Dirección de la base de datos PostgreSQL proporcionada por Railway. |
| `LANGCHAIN_API_KEY` | Clave para enviar las trazas de cada conversación a LangSmith (para auditoría y depuración). |
| `LANGCHAIN_PROJECT` | Nombre del proyecto en LangSmith donde se agrupan las trazas. |
| `LANGCHAIN_TRACING_V2` | Debe estar en `true` para activar la trazabilidad. |
| `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | Credenciales OAuth2 para que el sistema envíe correos de alerta o los leads al Controller. |
| `CONTROLLER_EMAIL` | Dirección de correo del responsable que recibe los leads y las alertas de error. |
| `ODOO_HOST`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD`, `ODOO_PRODUCT_MODEL`, `ODOO_ONGRID_DOMAIN` | Parámetros de conexión al sistema ERP Odoo para consultar datos maestros de productos. |

**Servicio: `cliente-humano` (Frontend Web Streamlit)**
*Contiene el archivo `streamlit_app.py`.*
Es un cliente tonto; solo necesita saber dónde está la API y la contraseña.

| Variable de Entorno | Descripción y Propósito |
| :--- | :--- |
| `BACKEND_URL` | La URL pública del servicio `cliente-api` en Railway (ej. `https://cliente-api.up.railway.app`). |
| `CHATBOT_MASTER_API_KEY` | Debe ser exactamente la misma clave que se configuró en el servicio de la API. |
| `OPENAI_API_KEY` | **Ya no es necesaria** en esta versión (la interfaz no usa IA directamente). |
| `ONTOLOGY_JSON_PATH` | **Ya no es necesaria** en la interfaz. |

## 4. Métodos de Implementación por Canal de Consumo

Este capítulo es una guía práctica para desplegar y utilizar JARVI en sus tres modalidades.

### 4.1 Canal Web Humano (Streamlit)

**Objetivo:** Un usuario final (cliente potencial o vendedor) interactúa con Jarvi mediante un chat en un navegador web.

1.  **Despliegue en Railway:**
    *   Asegúrese de que el servicio `cliente-humano` esté configurado con las variables de entorno (`BACKEND_URL`, `CHATBOT_MASTER_API_KEY`).
    *   La URL de acceso es la que proporciona Railway para este servicio.
2.  **Uso de la Interfaz:**
    *   **Inicio:** Al abrir la web, Jarvi se presenta y ofrece un menú de opciones (1-7). Se genera automáticamente un `thread_id` único para esta conversación.
    *   **Conversación por Texto:** Escriba su consulta en el campo de chat inferior ("¿Qué solución necesitas hoy?") y presione Enter. Observará cómo la respuesta se escribe letra por letra.
    *   **Entrada de Voz:** Presione el botón del micrófono 🎤, hable y suelte. Verá un indicador de "Transcribiendo mensaje...". Automáticamente, su voz se convertirá en un mensaje de texto que Jarvi responderá.
    *   **Respuesta por Voz:** Tras recibir una respuesta textual, y si el modo voz estaba activo, el sistema generará un audio que se reproducirá automáticamente.
    *   **Análisis de Factura:** En la sección "Cargar Factura Eléctrica", suba una foto de su recibo. La interfaz la enviará a la API para extraer los datos y los inyectará en la conversación.

### 4.2 Canal de Automatización (n8n)

**Objetivo:** Integrar a Jarvi en un flujo de trabajo automatizado, por ejemplo, cuando un cliente escribe a un número de WhatsApp, n8n recibe el mensaje, consulta a Jarvi y envía la respuesta.

1.  **Configuración del Webhook de n8n:**
    *   Cree un flujo en n8n que reciba el mensaje de entrada.
    *   Añada un nodo "HTTP Request".
    *   **Método:** `POST`
    *   **URL:** `https://[URL-DE-TU-SERVICIO-CLIENTE-API]/chat`
    *   **Headers:**
        *   `Authorization: Bearer [TU CHATBOT_MASTER_API_KEY]`
        *   `Content-Type: application/json`
    *   **Cuerpo (JSON):**
        ```json
        {
          "thread_id": "{{ $('Nodo-Anterior').item.json.thread_id }}",
          "message": "{{ $('Nodo-Anterior').item.json.mensaje_del_cliente }}"
        }
