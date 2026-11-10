from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.core.config import settings
from app.domain.models import DocumentFileDomain


class EmbeddingService:
    """Genera embeddings documentales respetando la dimensión configurada."""

    def __init__(self):
        self.embedding_model = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY or None,
            output_dimensionality=settings.EMBEDDING_DIMENSIONS
        )

    def generar_embeddings(self, documento: DocumentFileDomain) -> None:
        print(f"Generando embeddings para: {documento.nombre}")
        if not documento.chunks:
            print("El documento no tiene chunks.")
            return

        textos = [chunk.document.page_content for chunk in documento.chunks]
        if not textos:
            print("El documento no contiene texto para generar embeddings.")
            return

        vectores = self.embedding_model.embed_documents(textos)
        if not vectores:
            print("No se generaron embeddings para el documento.")
            return

        for chunk, vector in zip(documento.chunks, vectores):
            chunk.embedding = vector

        print(f"Se generaron {len(vectores)} embeddings.")
        print(f"Dimensión del vector: {len(vectores[0])}")
