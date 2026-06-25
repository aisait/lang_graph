# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class ISOConfigValidator:
    """Validador estricto de variables de entorno según ISO 27001."""
    REQUIRED_ENV = [
        "OPENAI_API_KEY", "GMAIL_REFRESH_TOKEN", "GMAIL_CLIENT_ID", 
        "GMAIL_CLIENT_SECRET", "APICHAT_TOKEN", "CONTROLLER_EMAIL"
    ]
    
    @classmethod
    def validar_entorno(cls):
        missing = [env for env in cls.REQUIRED_ENV if not os.getenv(env)]
        if missing:
            raise ImportError(f"❌ Falla de Seguridad ISO 27001: Faltan variables críticas: {missing}")

# Ejecutar validación inmediata en la importación
ISOConfigValidator.validar_entorno()

# API Acruxlab / Odoo WhatsApp
APICHAT_TOKEN = os.getenv("APICHAT_TOKEN")
APICHAT_ENDPOINT = os.getenv("APICHAT_ENDPOINT", "https://api.acruxlab.net/prod/v2/odoo")
APICHAT_INSTANCE = os.getenv("APICHAT_INSTANCE", "aisa_816")

# Parámetros Odoo ERP (Railway Environment Variables)
ODOO_HOST = os.getenv("ODOO_HOST", "34.75.123.223")
ODOO_DB = os.getenv("ODOO_DB", "aisa_prod")
ODOO_USER = os.getenv("ODOO_USER", "agente_n8n")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "Agente*2025")
ODOO_PRODUCT_MODEL = os.getenv("ODOO_PRODUCT_MODEL", "product.template")
ODOO_ONGRID_DOMAIN = os.getenv("ODOO_ONGRID_DOMAIN", '[["sale_ok","=",True],["type","=","product"]]')

CONTROLLER_EMAIL = os.getenv("CONTROLLER_EMAIL", "joseardon@aisa.com.gt")
SMTP_USER = os.getenv("SMTP_USER", "AISA Bot")
