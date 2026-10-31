import os
from pathlib import Path
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from app.domain.models import DocumentFileDomain
from app.utils.hash_utils import generar_document_id
from app.core.config import settings


class DocumentLoader:
    def __init__(self):
        self.documents_folder = Path(settings.DOCUMENTS_FOLDER).resolve()

    def cargar_documentos(self):
        archivos = []
        if not self.documents_folder.exists() or not self.documents_folder.is_dir():
            print(f"Advertencia: No existe el directorio en '{self.documents_folder}'.")
            return archivos

        for file_path in self.documents_folder.iterdir():
            if not file_path.is_file():
                continue

            documentos = []
            if file_path.suffix.lower() == ".md":
                loader = TextLoader(str(file_path), encoding="utf-8")
                documentos = loader.load()
            elif file_path.suffix.lower() == ".pdf":
                loader = PyPDFLoader(str(file_path))
                documentos = loader.load()

            if documentos:
                archivo = DocumentFileDomain(
                    nombre=file_path.name,
                    ruta=str(file_path),
                    document_id=generar_document_id(str(file_path)),
                    documentos=documentos
                )
                archivos.append(archivo)

        return archivos
