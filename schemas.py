from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class ChatRequest(BaseModel):
    thread_id: str = Field(..., description="ID único de sesión del cliente")
    message: str = Field(..., description="Contenido del mensaje del cliente")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ChatResponse(BaseModel):
    response: str
    run_id: str
    status: str = "success"
