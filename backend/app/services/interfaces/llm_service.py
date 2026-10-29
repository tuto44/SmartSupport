from abc import ABC, abstractmethod
from typing import List, Optional


class ILLMService(ABC):
    """
    Contrato abstracto para proveedores de Inteligencia Artificial.

    Encapsula las tres capacidades de IA utilizadas por RagService:
    - Generación de embeddings vectoriales
    - Análisis multimodal de imágenes
    - Generación de respuestas de texto

    Cualquier proveedor (Gemini, OpenAI, Azure, mock de tests) debe implementar
    estos tres métodos para ser inyectable en RagService.
    """

    @abstractmethod
    async def generar_embedding(self, texto: str) -> List[float]:
        """Genera un vector numérico representativo del texto dado."""
        ...

    @abstractmethod
    async def extraer_descripcion_imagen(self, image_base64: str) -> str:
        """
        Extrae términos técnicos clave de una captura visual.
        Recibe la imagen en base64 (con o sin prefijo data:image/...) y
        devuelve una descripción textual concisa.
        """
        ...

    @abstractmethod
    async def generar_respuesta(self, prompt: str, image_base64: Optional[str] = None) -> str:
        """
        Genera la respuesta del asistente a partir de un prompt construido
        y, opcionalmente, una imagen adjunta en base64.
        """
        ...

