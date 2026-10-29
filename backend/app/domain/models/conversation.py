from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ConversationState:
    """Estado persistido de una conversación activa (objetivo raíz y contexto activo)."""
    root_issue: str | None = None
    last_context: str | None = None


@dataclass
class MessageDomain:
    """Entidad de dominio que representa un mensaje individual del historial."""
    id: int | None = None
    conversation_id: str = ""
    user_name: str = ""
    role: str = ""
    content: str = ""
    created_at: datetime | None = None


@dataclass
class ConversationDomain:
    """Entidad de dominio que representa una conversación completa con su historial."""
    id: str
    user_id: str
    user_name: str
    title: str = "Nueva conversación"
    root_issue: str | None = None
    last_context: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: List[MessageDomain] = field(default_factory=list)

