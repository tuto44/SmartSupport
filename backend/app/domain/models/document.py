from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List


@dataclass
class DocumentChunkDomain:
    """Fragmento de documento con su vector de embedding asociado."""
    document: Any
    embedding: list[float] | None = None
    chunk_index: int = 0
    chunk_id: int | None = None
    page: int | None = None
    score: float | None = None


@dataclass
class DocumentFileDomain:
    """Archivo de documento con metadatos de indexación."""
    nombre: str
    ruta: str
    document_id: str | None = None
    hash_documento: str | None = None
    documentos: List[Any] = field(default_factory=list)
    chunks: List[DocumentChunkDomain] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    embedding_count: int = 0
    indexed_at: datetime | None = None
    status: str = "pendiente"

