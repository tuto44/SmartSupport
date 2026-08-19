from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import EMBEDDING_MODEL
from app.models.document_file import DocumentFile

class EmbeddingService:
    def __init__(self):
        self.embedding_model = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL)
        
    def generar_embeddings(self, documento: DocumentFile):
            print(f"Generando embeddings para: {documento.nombre}")
            if not documento.chunks:
                print("El documento no tiene chunks.")
                return
            textos = [
                chunk.document.page_content
                for chunk in documento.chunks]
            vectores = self.embedding_model.embed_documents(textos)
            for chunk, vector in zip(documento.chunks, vectores):
                chunk.embedding = vector
            print(f"Se generaron {len(vectores)} embeddings.")
            print(f"Dimensión del vector: {len(vectores[0])}")