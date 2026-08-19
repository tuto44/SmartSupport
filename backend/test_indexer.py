from app.services.indexer import Indexer

indexer = Indexer()

indexer.indexar_documentos()

print(indexer.loader)

print(indexer.qdrant)