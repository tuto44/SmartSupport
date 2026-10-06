from pydantic import BaseModel
from typing import List, Optional

class MensajeHistorial(BaseModel):
    role: str  # "user" o "assistant"
    content: str

class ChatRequest(BaseModel):
    question: str
    historial: List[MensajeHistorial] = []  # PHP nos envía los últimos mensajes
    user_name: Optional[str] = "Usuario"
    image_base64: Optional[str] = None

class ChatResponse(BaseModel):
    status: str
    answer: str