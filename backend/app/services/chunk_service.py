from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.models.document_file import DocumentFile
from app.utils.hash_utils import generar_chunk_id
from app.models.document_chunk import DocumentChunk
from app.config import (CHUNK_SIZE,CHUNK_OVERLAP)

class ChunkService:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        
    def generar_chunks(self, documento):
        print(f"Generando chunks para: {documento.nombre}")
        documento.chunks.clear()
        chunks = self.text_splitter.split_documents(documento.documentos)
        
        for indice ,chunk in enumerate(chunks):
            pagina = chunk.metadata.get("page")
            document_chunk = DocumentChunk(
                document = chunk,
                chunk_index = indice,
                chunk_id = generar_chunk_id(documento.document_id, indice),
                page = pagina
            )
            documento.chunks.append(document_chunk)
        print(f"Se generaron {len(documento.chunks)}")
        
        for chunk in documento.chunks:
            print(f"Chunk {chunk.chunk_index} - Página: {chunk.page} - Caracteres: {len(chunk.document.page_content)}" )