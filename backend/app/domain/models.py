from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ConversationState:
    root_issue: str | None = None
    last_context: str | None = None


@dataclass
class MessageDomain:
    id: int | None = None
    conversation_id: str = ""
    user_name: str = ""
    role: str = ""
    content: str = ""
    created_at: datetime | None = None


@dataclass
class ConversationDomain:
    id: str
    user_id: str
    user_name: str
    title: str = "Nueva conversación"
    root_issue: str | None = None
    last_context: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: List[MessageDomain] = field(default_factory=list)


@dataclass
class DocumentChunkDomain:
    document: any
    embedding: list[float] | None = None
    chunk_index: int = 0
    chunk_id: int | None = None
    page: int | None = None
    score: float | None = None


@dataclass
class DocumentFileDomain:
    nombre: str
    ruta: str
    document_id: str | None = None
    hash_documento: str | None = None
    documentos: List[any] = field(default_factory=list)
    chunks: List[DocumentChunkDomain] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    embedding_count: int = 0
    indexed_at: datetime | None = None
    status: str = "pendiente"
