from app.loaders.document_loader import DocumentLoader
from app.database.qdrant_manager import QdrantManager
from app.services.chunk_service import ChunkService
from app.services.embedding_service import EmbeddingService
from app.utils.hash_utils import calcular_hash


class Indexer:

    def __init__(self):
        self.loader = DocumentLoader()
        self.qdrant = QdrantManager()
        self.chunk_service = ChunkService()
        self.embedding_service = EmbeddingService()

    def indexar_documentos(self):
        documentos = self.loader.cargar_documentos()
        print(f"\nSe encontraron {len(documentos)} documentos.\n")
        for documento in documentos:
            print("=" * 60)
            print(f"Procesando: {documento.nombre}")
            # Calcular hash
            documento.hash_documento = calcular_hash(documento.ruta)
            # Verificar si ya existe
            existe = self.qdrant.obtener_documento(documento.document_id)
            if existe:
                if existe["hash_documento"] == documento.hash_documento:
                    print("El documento no cambió. Se omite.")
                    continue
                print("El documento cambió. Actualizando...")
                self.qdrant.eliminar_documento(documento.document_id)
            # Generar chunks
            self.chunk_service.generar_chunks(documento)
            # Generar embeddings
            self.embedding_service.generar_embeddings(documento)
            # Crear colección si aún no existe
            if self.qdrant.vector_size is None:
                vector_size = len(documento.chunks[0].embedding)
                self.qdrant.crear_coleccion_si_no_existe(vector_size)
            # Guardar documento
            self.qdrant.guardar_documento(documento)
        print("\nINDEXACIÓN FINALIZADA.")