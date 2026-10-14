import os
from pathlib import Path
from langchain_community.document_loaders import (TextLoader, PyPDFLoader)
from app.models.document_file import DocumentFile
from app.utils.hash_utils import generar_document_id
from app.config import DOCUMENTS_FOLDER

class DocumentLoader:
    
    def __init__(self):
        if os.path.exists(DOCUMENTS_FOLDER):
            self.documents_folder = DOCUMENTS_FOLDER
        else:
            base_backend = Path(__file__).resolve().parent.parent.parent
            self.documents_folder = str(base_backend / "documentos")
        
    def cargar_documentos(self):
        archivos = []

        if not os.path.exists(self.documents_folder):
            print(f"Advertencia: No existe la carpeta '{self.documents_folder}'.")
            return archivos

        for file_name in os.listdir(self.documents_folder):
            file_path = os.path.join(
                self.documents_folder, file_name)
            documentos = []
            if file_name.endswith(".md"):
                loader = TextLoader(file_path, encoding="utf-8")
                documentos = loader.load()
            elif file_name.endswith(".pdf"):
                loader = PyPDFLoader(file_path)
                documentos = loader.load()
                
            if documentos:
                archivo = DocumentFile(
                    nombre=file_name,
                    ruta=file_path,
                    document_id=generar_document_id(file_path),
                    documentos=documentos
                )
                archivos.append(archivo)
                
        return archivos