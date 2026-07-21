"""
config.py
Módulo de configuración central de JARVI 2.0.
Carga variables de entorno, valida requisitos mínimos y expone constantes.
"""
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    chatbot_master_api_key: str

    # Langfuse
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str = "https://langfuse-web-production-2599.up.railway.app/"
    langfuse_tracing_environment: str = "production"

    # Bases de datos
    database_url: str = ""   # Opcional, para checkpoints de LangGraph
    ctfom_database_url: str
    bi_database_url: str

    # Redis
    redis_url: str = ""
    redis_ttl: int = 604800

    # Odoo
    odoo_host: str = "34.75.123.223"
    odoo_db: str = "aisa_prod"
    odoo_user: str = "agente_n8n"
    odoo_password: str = "Agente*2025"
    odoo_product_model: str = "product.template"
    odoo_ongrid_domain: str = '[["sale_ok","=",True],["type","=","product"]]'

    # Correo
    controller_email: str = "joseardon@aisa.com.gt"
    smtp_user: str = "AISA Bot"
    gmail_refresh_token: str
    gmail_client_id: str
    gmail_client_secret: str

    # Webhooks
    apichat_instance: str = ""
    apichat_endpoint: str = ""
    apichat_token: str = ""

    # Otros
    backend_url: str = "https://jarvi-backend-production.up.railway.app"
    n8n_webhook_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
