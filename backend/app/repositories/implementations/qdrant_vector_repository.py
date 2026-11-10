from typing import Any, List, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.core.config import settings
from app.repositories.interfaces.vector_repository import IVectorRepository


class QdrantVectorRepository(IVectorRepository):
    """Implementación de IVectorRepository utilizando QdrantClient."""

    def __init__(
        self,
        url: str | None = None,
        collection_name: str | None = None,
        api_key: str | None = None
    ):
        self.url = url or settings.QDRANT_URL
        self.collection_name = collection_name or settings.COLLECTION_NAME
        self.client = QdrantClient(
            url=self.url,
            api_key=api_key or settings.QDRANT_API_KEY
        )

    def _dimension_coleccion(self) -> int | None:
        """Obtiene la dimensión configurada de la colección (None si no aplica)."""
        info = self.client.get_collection(collection_name=self.collection_name)
        vectores = info.config.params.vectors
        size = getattr(vectores, "size", None)
        return int(size) if size is not None else None

    def crear_coleccion_si_no_existe(
        self,
        vector_size: int = settings.EMBEDDING_DIMENSIONS
    ) -> None:
        if self.client.collection_exists(collection_name=self.collection_name):
            dimension_actual = self._dimension_coleccion()
            if dimension_actual is not None and dimension_actual != vector_size:
                raise ValueError(
                    f"La colección Qdrant '{self.collection_name}' tiene "
                    f"{dimension_actual} dimensiones, pero la configuración espera "
                    f"{vector_size}. Ajusta EMBEDDING_DIMENSIONS o reindexa la "
                    "colección con la dimensión correcta."
                )
            print(
                f"[QDRANT] Colección '{self.collection_name}' ya existe "
                f"(dimensión: {dimension_actual})."
            )
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE
            )
        )
        print(f"[QDRANT] Colección '{self.collection_name}' creada (dimensión: {vector_size}).")

    def obtener_documento(self, document_id: str) -> Optional[dict]:
        if not self.client.collection_exists(collection_name=self.collection_name):
            return None

        try:
            puntos, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id)
                        )
                    ]
                ),
                limit=1
            )
            if not puntos:
                return None
            return puntos[0].payload
        except Exception as e:
            print(f"[QDRANT ERROR] Aviso consultando documento: {e}")
            return None

    def guardar_documento(self, documento: Any) -> None:
        print(f"[QDRANT] Guardando documento: {documento.nombre}")
        points = []
        for chunk in documento.chunks:
            point = models.PointStruct(
                id=chunk.chunk_id,
                vector=chunk.embedding,
                payload={
                    "document_id": documento.document_id,
                    "document_name": documento.nombre,
                    "hash_documento": documento.hash_documento,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                    "page_content": chunk.document.page_content
                }
            )
            points.append(point)

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        print(f"[QDRANT] Se guardaron {len(points)} chunks correctamente.")

    def eliminar_documento(self, document_id: str) -> None:
        if not self.client.collection_exists(collection_name=self.collection_name):
            return

        print(f"[QDRANT] Eliminando documento: {document_id}")
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            )
        )
        print("[QDRANT] Documento eliminado correctamente.")

    def buscar_similares(self, embedding: List[float], limite: int = settings.TOP_K_RESULTS) -> List[Any]:
        if not self.client.collection_exists(collection_name=self.collection_name):
            return []

        resultados = self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limite
        )
        return resultados.points

    def obtener_estadisticas(self) -> Optional[Any]:
        if not self.client.collection_exists(collection_name=self.collection_name):
            return None
        return self.client.get_collection(collection_name=self.collection_name)
