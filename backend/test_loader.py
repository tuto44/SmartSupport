from app.loaders.document_loader import DocumentLoader

loader = DocumentLoader()

archivos = loader.cargar_documentos()

print(f"Archivos encontrados: {len(archivos)}")

for archivo in archivos:

    print("-" * 40)

    print(archivo.nombre)

    print(archivo.ruta)

    print(len(archivo.documentos))