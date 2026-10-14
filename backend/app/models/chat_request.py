from pydantic import BaseModel


class ChatRequest(BaseModel):
    user_name: str = "Usuario"
    question: str = ""
    conversation_id: str | None = None
    user_id: str | None = None
    image_base64: str | None = None