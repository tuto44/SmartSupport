from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.models.document_file import DocumentFile
from app.config import (QDRANT_URL, COLLECTION_NAME,TOP_K_RESULTS, MIN_SIMILARITY_SCORE)

class QdrantManager:

    def __init__(self):
        self.client=QdrantClient(url=QDRANT_URL)
        self.collection_name= COLLECTION_NAME
        self.vector_size = None


    def crear_coleccion_si_no_existe(self, vector_size: int):
        self.vector_size = vector_size
        if self.client.collection_exists(
            collection_name=self.collection_name):
            print(f"Colección '{self.collection_name}' ya existe.")
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE))
        print(f"Colección '{self.collection_name}' creada correctamente.")
        
        
    
    
    def obtener_documento(self,document_id :str):
        print(f"Buscando documento con ID: {document_id}")
        puntos, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id)
                )]
            ),
            limit=1)
        if not puntos:
            print(f"Documento no encontadro")
            return None
        print(f"Documento encontrado:")
        return puntos[0].payload
    
    
    
    def guardar_documento(self, documento: DocumentFile):
        print(f"Guardando documento: {documento.nombre}")
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
                    "page_content": chunk.document.page_content})
            points.append(point)
        self.client.upsert(
            collection_name=self.collection_name,
            points=points)
        print(f"Se guardaron {len(points)} chunks correctamente.")
        

    def eliminar_documento(self, document_id: str):
        print(f"Eliminando documento: {document_id}")
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id))])
        )
    )
        print("Documento eliminado correctamente.")

    def buscar_similares(self, embedding: list[float], limite: int = TOP_K_RESULTS):
        resultados = self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limite)
        return resultados.points
    
    def obtener_estadisticas(self):
        info = self.client.get_collection(
            collection_name=self.collection_name)
        return info
