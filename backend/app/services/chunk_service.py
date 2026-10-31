from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import settings
from app.domain.models import DocumentFileDomain, DocumentChunkDomain
from app.utils.hash_utils import generar_chunk_id

class ChunkService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP)
        
    def generar_chunks(self, documento: DocumentFileDomain):
        print(f"Generando chunks para: {documento.nombre}")
        documento.chunks.clear()
        chunks = self.text_splitter.split_documents(documento.documentos)
        
        for indice, chunk in enumerate(chunks):
            pagina = chunk.metadata.get("page")
            document_chunk = DocumentChunkDomain(
                document=chunk,
                chunk_index=indice,
                chunk_id=generar_chunk_id(documento.document_id, indice),
                page=pagina
            )
            documento.chunks.append(document_chunk)
        print(f"Se generaron {len(documento.chunks)}")