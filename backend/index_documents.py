from app.services.indexer import Indexer


def main():
    print("=" * 60)
    print("INICIANDO INDEXACIÓN DE DOCUMENTOS")
    print("=" * 60)

    indexer = Indexer()
    indexer.indexar_documentos()

    print("=" * 60)
    print("INDEXACIÓN FINALIZADA")
    print("=" * 60)


if __name__ == "__main__":
    main()