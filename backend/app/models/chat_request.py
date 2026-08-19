from pydantic import BaseModel


class ChatRequest(BaseModel):
    user_name: str
    question: str