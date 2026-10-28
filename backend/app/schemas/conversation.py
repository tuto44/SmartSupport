from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    conversation_id: str
    user_id: str
    user_name: str
    role: str
    content: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    role: str
    content: str
    created_at: datetime | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_name: str
    title: str | None = None
    root_issue: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationStateUpdate(BaseModel):
    root_issue: str | None = None
    last_context: str | None = None
