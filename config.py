import os
from dotenv import load_dotenv

load_dotenv()

class ISOConfigValidator:
    """Validador condicional: Solo exige tokens si es entorno Backend."""
    REQUIRED_ENV = ["OPENAI_API_KEY", "GMAIL_REFRESH_TOKEN", "CONTROLLER_EMAIL"]
    
    @classmethod
    def validar_entorno(cls):
        # Si no es backend, no validamos tokens de Odoo/API
        if os.getenv("IS_BACKEND") != "True":
            return
        missing = [env for env in cls.REQUIRED_ENV if not os.getenv(env)]
        if missing:
            raise ImportError(f"❌ Falla de Seguridad ISO 27001: Faltan variables críticas: {missing}")

ISOConfigValidator.validar_entorno()

# Parámetros Odoo ERP
ODOO_HOST = os.getenv("ODOO_HOST", "34.75.123.223")
ODOO_DB = os.getenv("ODOO_DB", "aisa_prod")
ODOO_USER = os.getenv("ODOO_USER", "agente_n8n")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "Agente*2025")
ODOO_PRODUCT_MODEL = os.getenv("ODOO_PRODUCT_MODEL", "product.template")
ODOO_ONGRID_DOMAIN = os.getenv("ODOO_ONGRID_DOMAIN", '[["sale_ok","=",True],["type","=","product"]]')

CONTROLLER_EMAIL = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
SMTP_USER = os.getenv("SMTP_USER", "AISA Bot")

# Webhook n8n (Nueva fuente de verdad)
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
