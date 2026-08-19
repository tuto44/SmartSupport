import hashlib

def calcular_hash(ruta_archivo: str) -> str:
    sha256 = hashlib.sha256()

    with open(ruta_archivo, "rb") as archivo:

        for bloque in iter(lambda: archivo.read(4096), b""):
            sha256.update(bloque)

    return sha256.hexdigest()

def generar_document_id(ruta_archivo):
    ruta_normalizada = ruta_archivo.replace("\\", "/")
    return hashlib.sha256(ruta_normalizada.encode("utf-8")).hexdigest()

def generar_chunk_id(document_id: str, chunk_index: int) -> int:
    texto = f"{document_id}_{chunk_index}"

    hash_hex = hashlib.sha256(
        texto.encode("utf-8")
    ).hexdigest()

    return int(hash_hex[:16], 16)