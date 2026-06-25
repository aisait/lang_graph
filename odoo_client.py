# odoo_client.py
import streamlit as st
from xmlrpc import client as xmlrpc_client
import json
import config
from audit import auditar_fase

@st.cache_resource
def obtener_uid_odoo():
    """Establece y cachea la sesión de autenticación con el ERP."""
    try:
        common = xmlrpc_client.ServerProxy(f"http://{config.ODOO_HOST}:8069/xmlrpc/2/common")
        return common.authenticate(config.ODOO_DB, config.ODOO_USER, config.ODOO_PASSWORD, {})
    except Exception as e:
        st.warning(f"⚠️ Alerta de Conectividad ERP: No se pudo autenticar en Odoo: {e}")
        return None

@auditar_fase(nombre_fase="Capa de Abstracción Odoo RPC", criticidad="ALTA")
def ejecutar_odoo(modelo: str, metodo: str, *args, **kwargs):
    """Ejecutor genérico parametrizado y protegido contra caídas de red."""
    uid = obtener_uid_odoo()
    if uid is None:
        return None
    try:
        models = xmlrpc_client.ServerProxy(f"http://{config.ODOO_HOST}:8069/xmlrpc/2/object")
        return models.execute_kw(config.ODOO_DB, uid, config.ODOO_PASSWORD, modelo, metodo, args, kwargs)
    except Exception as e:
        st.error(f"Error de ejecución en modelo ERP {modelo}: {e}")
        return None

@st.cache_data(ttl=600)
def obtener_productos_on_grid_odoo():
    """Consulta la ficha técnica de productos On‑Grid desde Odoo de forma segura."""
    try:
        domain = json.loads(config.ODOO_ONGRID_DOMAIN)
    except Exception:
        domain = [("sale_ok", "=", True), ("type", "=", "product")]
    
    # Campos requeridos por el Consejo de Auditoría para análisis de ciclo completo
    fields = ["name", "description_sale", "list_price", "website_url", "default_code"]
    productos = ejecutar_odoo(config.ODOO_PRODUCT_MODEL, "search_read", [domain], {"fields": fields, "limit": 50})
    return productos
