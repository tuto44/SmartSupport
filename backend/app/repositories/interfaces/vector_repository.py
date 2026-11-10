from abc import ABC, abstractmethod
from typing import Any, List, Optional
from app.domain.models import DocumentFileDomain


class IVectorRepository(ABC):
    """Contrato abstracto para el repositorio vectorial."""

    @abstractmethod
    def crear_coleccion_si_no_existe(self, vector_size: int = 768) -> None:
        """Crea la colección vectorial si aún no existe."""
        pass

    @abstractmethod
    def obtener_documento(self, document_id: str) -> Optional[dict]:
        """Obtiene la metadata de un documento indexado."""
        pass

    @abstractmethod
    def guardar_documento(self, documento: Any) -> None:
        """Guarda los chunks y embeddings de un documento."""
        pass

    @abstractmethod
    def eliminar_documento(self, document_id: str) -> None:
        """Elimina todos los vectores de un documento."""
        pass

    @abstractmethod
    def buscar_similares(self, embedding: List[float], limite: int = 5) -> List[Any]:
        """Busca vectores similares al embedding provisto."""
        pass

    @abstractmethod
    def obtener_estadisticas(self) -> Optional[Any]:
        """Retorna estadísticas de la colección."""
        pass
