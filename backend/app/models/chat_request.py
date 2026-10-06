from pydantic import BaseModel


class ChatRequest(BaseModel):
    user_name: str
    question: str
    conversation_id: str | None = None
    user_id: str | None = None