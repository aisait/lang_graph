"""
schemas.py
═══════════════════════════════════════════════════════════════════════
Contratos de datos (Pydantic) para la API central.
Se añaden modelos para la telemetría enriquecida (ISO/IEC 25010 - mantenibilidad).

Pruebas de caja negra (ISO/IEC 29119):
    BC‑T05: Validación de schema → verificar que los nuevos modelos rechacen datos inválidos.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="ID único de sesión del cliente.")
    message: str = Field(..., description="Contenido del mensaje del cliente.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ChatResponse(BaseModel):
    response: str
    run_id: str
    status: str = "success"

# Nuevos modelos para telemetría enriquecida (ISO 25010 - mantenibilidad)
class TelemetryContext(BaseModel):
    """Contexto de telemetría inyectado en CTFOM y Redis."""
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
