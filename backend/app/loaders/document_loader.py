import os
from pathlib import Path
from langchain_community.document_loaders import (TextLoader, PyPDFLoader)
from app.models.document_file import DocumentFile
from app.utils.hash_utils import generar_document_id
from app.core.config import settings

class DocumentLoader:
    
    def __init__(self):
        # Buscar en la carpeta configurada y si está vacía o no existe, verificar la raíz del proyecto
        base_backend = Path(__file__).resolve().parent.parent.parent
        root_dir = base_backend.parent
        
        candidatos = [
            Path(settings.DOCUMENTS_FOLDER).resolve(),
            base_backend / "documentos",
            root_dir / "documentos"
        ]
        
        self.documents_folder = str(base_backend / "documentos")
        for ruta in candidatos:
            if ruta.exists() and any(ruta.iterdir()):
                self.documents_folder = str(ruta)
                break
        
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