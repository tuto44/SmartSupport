from app.database.qdrant_manager import QdrantManager

qdrant = QdrantManager()

qdrant.crear_coleccion_si_no_existe(3072)