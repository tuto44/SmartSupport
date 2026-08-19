from dataclasses import dataclass, field

from langchain_core.documents import Document


@dataclass
class DocumentChunk:


    document: Document

    embedding: list[float] | None = None

    chunk_index: int = 0
    
    chunk_id: int | None = None

    page: int | None = None

    score: float | None = None