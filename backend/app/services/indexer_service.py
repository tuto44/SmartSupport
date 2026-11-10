from typing import Optional
from app.loaders.document_loader import DocumentLoader
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.repositories.implementations.qdrant_vector_repository import QdrantVectorRepository
from app.services.chunk_service import ChunkService
from app.services.embedding_service import EmbeddingService
from app.utils.hash_utils import calcular_hash


class IndexerService:
    """
    Servicio de indexación de documentos en el almacén de vectores.
    Desacoplado mediante inyección de dependencias (IVectorRepository).
    """

    def __init__(
        self,
        vector_repo: Optional[IVectorRepository] = None,
        loader: Optional[DocumentLoader] = None,
        chunk_service: Optional[ChunkService] = None,
        embedding_service: Optional[EmbeddingService] = None
    ):
        self.vector_repo = vector_repo or QdrantVectorRepository()
        self.loader = loader or DocumentLoader()
        self.chunk_service = chunk_service or ChunkService()
        self.embedding_service = embedding_service or EmbeddingService()

    def indexar_documentos(self, vector_size: int = 768) -> None:
        documentos = self.loader.cargar_documentos()
        print(f"\n[INDEXER] Se encontraron {len(documentos)} documentos.\n")

        if not documentos:
            print("[INDEXER] No se encontraron documentos en la carpeta configurada.")
            return

        self.vector_repo.crear_coleccion_si_no_existe(vector_size=vector_size)

        for documento in documentos:
            print("=" * 60)
            print(f"[INDEXER] Procesando: {documento.nombre}")

            documento.hash_documento = calcular_hash(documento.ruta)

            existe = self.vector_repo.obtener_documento(documento.document_id)
            if existe:
                if existe.get("hash_documento") == documento.hash_documento:
                    print(f"[INDEXER] Documento '{documento.nombre}' no cambió. Se omite.")
                    continue
                print(f"[INDEXER] Documento '{documento.nombre}' cambió. Reemplazando chunks anteriores...")
                self.vector_repo.eliminar_documento(documento.document_id)

            self.chunk_service.generar_chunks(documento)

            if not documento.chunks:
                print(f"[INDEXER] Advertencia: '{documento.nombre}' no contiene chunks. Se omite.")
                continue

            self.embedding_service.generar_embeddings(documento)
            self.vector_repo.guardar_documento(documento)

        print("\n" + "=" * 60)
        print("[INDEXER] INDEXACIÓN FINALIZADA CON ÉXITO")
        print("=" * 60)
