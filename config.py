"""
config.py - Configuración central con mapeo explícito de variables de entorno.
Todos los campos tienen valores predeterminados para evitar fallos.
"""
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

load_dotenv()

class Settings(BaseSettings):
    # API Keys
    chatbot_master_api_key: str = Field(default="sk_dev_fallback", env="CHATBOT_MASTER_API_KEY")
    
    # OpenAI (fallback a _1, _2, _3)
    openai_api_key_1: str = Field(default="", env="OPENAI_API_KEY_1")
    openai_api_key_2: str = Field(default="", env="OPENAI_API_KEY_2")
    openai_api_key_3: str = Field(default="", env="OPENAI_API_KEY_3")
    
    @property
    def openai_api_key(self) -> str:
        for key in [self.openai_api_key_1, self.openai_api_key_2, self.openai_api_key_3]:
            if key:
                return key
        return os.getenv("OPENAI_API_KEY", "")

    # Langfuse
    langfuse_public_key: str = Field(default="", env="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", env="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", env="LANGFUSE_HOST")
    langfuse_tracing_environment: str = Field(default="production", env="LANGFUSE_TRACING_ENVIRONMENT")

    # Bases de datos
    ctfom_database_url: str = Field(default="", env="CTFOM_DATABASE_URL")
    bi_database_url: str = Field(default="", env="BI_DATABASE_URL")
    database_url: str = Field(default="", env="DATABASE_URL")

    # Redis
    redis_url: str = Field(default="", env="REDIS_URL")
    redis_ttl: int = Field(default=604800, env="REDIS_TTL")

    # Odoo
    odoo_host: str = Field(default="34.75.123.223", env="ODOO_HOST")
    odoo_db: str = Field(default="aisa_prod", env="ODOO_DB")
    odoo_user: str = Field(default="agente_n8n", env="ODOO_USER")
    odoo_password: str = Field(default="Agente*2025", env="ODOO_PASSWORD")
    odoo_product_model: str = Field(default="product.template", env="ODOO_PRODUCT_MODEL")
    odoo_ongrid_domain: str = Field(default='[["sale_ok","=",True],["type","=","product"]]', env="ODOO_ONGRID_DOMAIN")

    # Correo
    controller_email: str = Field(default="joseardon@aisa.com.gt", env="CONTROLLER_EMAIL")
    smtp_user: str = Field(default="AISA Bot", env="SMTP_USER")
    gmail_refresh_token: str = Field(default="", env="GMAIL_REFRESH_TOKEN")
    gmail_client_id: str = Field(default="", env="GMAIL_CLIENT_ID")
    gmail_client_secret: str = Field(default="", env="GMAIL_CLIENT_SECRET")

    # Webhooks
    n8n_webhook_url: str = Field(default="", env="N8N_WEBHOOK_URL")
    apichat_instance: str = Field(default="", env="APICHAT_INSTANCE")
    apichat_endpoint: str = Field(default="", env="APICHAT_ENDPOINT")
    apichat_token: str = Field(default="", env="APICHAT_TOKEN")

    # URLs públicas
    backend_url: str = Field(default="https://jarvi-backend-production.up.railway.app", env="BACKEND_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
