from dataclasses import dataclass, field
from app.models.document_chunk import DocumentChunk
from datetime import datetime
from typing import List
from langchain_core.documents import Document

@dataclass
class DocumentFile:

    nombre: str
    ruta: str
    
    document_id: str | None = None
    hash_documento: str | None = None

    documentos: List[Document] = field(default_factory=list)

    chunks: List[DocumentChunk] = field(default_factory=list)
    
    metadata: dict = field(default_factory=dict)
    
    embedding_count : int = 0
    
    indexed_at: datetime | None = None
    
    status: str = "pendiente"
    
    