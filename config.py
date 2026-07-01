"""
config.py
Módulo de configuración central de JARVI 2.0.
Carga variables de entorno, valida requisitos mínimos y expone constantes
para la conexión a Odoo, correo, webhooks, etc.
Estándares aplicados: ISO/IEC/IEEE 12207 (Ciclo de vida), ISO/IEC 26514 (Documentación),
ISO/IEC 25010 (Calidad), ISO/IEC 29119 (Pruebas de caja negra).
"""

import os
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Carga de variables desde archivo .env (solo desarrollo local; en producción
# Railway las inyecta directamente).
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Validador condicional de entorno (ISO/IEC 27001 - Seguridad)
# ---------------------------------------------------------------------------
class ISOConfigValidator:
    """
    Verifica que las variables de entorno críticas estén presentes si el servicio
    se está ejecutando como backend (IS_BACKEND=True). Esto evita que la interfaz
    de usuario exija tokens que no necesita.

    Prueba de caja negra (ISO/IEC 29119):
        - Con IS_BACKEND=True y faltando OPENAI_API_KEY: debe lanzar ImportError.
        - Con IS_BACKEND=False (o no definida): no realiza ninguna validación.
        - Con todas las variables presentes: no hay excepción.
    """
    REQUIRED_ENV = ["OPENAI_API_KEY", "GMAIL_REFRESH_TOKEN", "CONTROLLER_EMAIL"]

    @classmethod
    def validar_entorno(cls):
        """
        Valida las variables de entorno requeridas solo en el backend.
        Lanza ImportError si alguna falta.
        """
        # Si no es backend, omitimos la validación (evita fallos en la UI)
        if os.getenv("IS_BACKEND") != "True":
            return
        missing = [env for env in cls.REQUIRED_ENV if not os.getenv(env)]
        if missing:
            raise ImportError(
                f"❌ Falla de Seguridad ISO 27001: Faltan variables críticas: {missing}"
            )

# Ejecutar validación inmediatamente al importar el módulo
ISOConfigValidator.validar_entorno()

# ---------------------------------------------------------------------------
# Parámetros de conexión a Odoo ERP
# ---------------------------------------------------------------------------
ODOO_HOST = os.getenv("ODOO_HOST", "34.75.123.223")
"""str: Dirección IP o dominio del servidor Odoo."""
ODOO_DB = os.getenv("ODOO_DB", "aisa_prod")
"""str: Nombre de la base de datos en Odoo."""
ODOO_USER = os.getenv("ODOO_USER", "agente_n8n")
"""str: Usuario de autenticación contra Odoo."""
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "Agente*2025")
"""str: Contraseña del usuario de Odoo."""
ODOO_PRODUCT_MODEL = os.getenv("ODOO_PRODUCT_MODEL", "product.template")
"""str: Modelo técnico de productos en Odoo."""
ODOO_ONGRID_DOMAIN = os.getenv(
    "ODOO_ONGRID_DOMAIN",
    '[["sale_ok","=",True],["type","=","product"]]'
)
"""str: Dominio Odoo en formato JSON para filtrar productos on‑grid."""

# ---------------------------------------------------------------------------
# Configuración de notificaciones (correo electrónico)
# ---------------------------------------------------------------------------
CONTROLLER_EMAIL = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
"""str: Dirección de correo del controlador que recibe alertas y leads."""
SMTP_USER = os.getenv("SMTP_USER", "AISA Bot")
"""str: Nombre o alias utilizado como remitente en los correos."""

# ---------------------------------------------------------------------------
# Webhook de n8n (punto de integración externo)
# ---------------------------------------------------------------------------
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
"""str | None: URL del webhook de n8n para disparar flujos automatizados."""

# ---------------------------------------------------------------------------
# Prueba de caja negra sugerida para todo el módulo:
#   - Ejecutar el script con 'python config.py' y verificar que no haya errores
#     de importación si las variables están configuradas.
#   - Modificar temporalmente el entorno para que falte OPENAI_API_KEY con
#     IS_BACKEND=True y comprobar que se lanza ImportError.
# ---------------------------------------------------------------------------
