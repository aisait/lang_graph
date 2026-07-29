"""
schemas.py - Contratos de datos (Pydantic) para la API central.
VERSIÓN 2.0.27 – Unificado para aceptar payload de n8n (chat_id, name, phone, record, url_n8n_audio).
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

class ChatRequest(BaseModel):
    # Alias para que 'chat_id' se mapee automáticamente a 'thread_id'
    thread_id: str = Field(..., alias='chat_id', description="ID único de sesión (chat_id de n8n).")
    message: str = Field(..., description="Contenido del mensaje del cliente.")

    # Campos específicos de n8n (opcionales)
    name: Optional[str] = Field(None, description="Nombre del cliente (desde n8n).")
    phone: Optional[str] = Field(None, description="Teléfono del cliente (desde n8n).")
    record: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Historial de conversación (desde n8n).")
    url_n8n_audio: Optional[str] = Field(None, description="URL del audio (desde n8n).")

    # Metadatos adicionales (para compatibilidad con debug u otros orígenes)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    class Config:
        populate_by_name = True   # permite usar 'thread_id' o 'chat_id' indistintamente
        extra = "allow"           # ignora campos extra sin romper validación

class ChatResponse(BaseModel):
    response: str
    run_id: str
    status: str = "success"

class TelemetryContext(BaseModel):
    trace_id: str
    span_id: str
    caso: str
    topologia: Optional[str] = None
    tipo_producto: Optional[str] = None
    productos_interes: List[Dict[str, Any]] = Field(default_factory=list)
    whatsapp: Optional[str] = None
    origen: str = "desconocido"
    llm_cost: Optional[float] = None
    llm_model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

class AudioRequest(BaseModel):
    thread_id: str

class ImageRequest(BaseModel):
    thread_id: str
    image_base64: str

class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"
