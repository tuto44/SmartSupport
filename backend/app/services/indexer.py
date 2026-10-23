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

        if not documentos:
            print("No se encontraron documentos en la carpeta configurada.")
            return

        Asegurar que la colección exista antes de cualquier consulta 

        VECTOR_SIZE = 768
        self.qdrant.crear_coleccion_si_no_existe(vector_size=VECTOR_SIZE)

        for documento in documentos:
            print("=" * 60)
            print(f"Procesando: {documento.nombre}")

            Calcular hash del archivo en disco
            documento.hash_documento = calcular_hash(documento.ruta)

            # 3. Verificar si ya existe en Qdrant y si su contenido cambió
            existe = self.qdrant.obtener_documento(documento.document_id)
            if existe:
                if existe.get("hash_documento") == documento.hash_documento:
                    print("El documento no cambió. Se omite.")
                    continue
                print("El documento cambió. Reemplazando chunks anteriores...")
                self.qdrant.eliminar_documento(documento.document_id)

            # 4. Dividir en chunks
            self.chunk_service.generar_chunks(documento)

            # 5. Validar que tenga contenido procesable
            if not documento.chunks:
                print(f"Advertencia: '{documento.nombre}' no contiene texto o chunks legibles. Se omite.")
                continue

            # 6. Generar embeddings con Gemini
            self.embedding_service.generar_embeddings(documento)

            # 7. Indexar en Qdrant
            self.qdrant.guardar_documento(documento)

        print("\n" + "=" * 60)
        print("INDEXACIÓN FINALIZADA CON ÉXITO")
        print("=" * 60)