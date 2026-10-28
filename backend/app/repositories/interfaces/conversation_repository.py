from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.models import ConversationDomain, ConversationState, MessageDomain


class IConversationRepository(ABC):
    """Contrato abstracto para el repositorio de persistencia de conversaciones."""

    @abstractmethod
    def crear_o_actualizar_conversacion(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        title: str = "Nueva conversación"
    ) -> ConversationDomain:
        """Crea o actualiza el registro de conversación."""
        pass

    @abstractmethod
    def obtener_conversacion(self, conversation_id: str) -> Optional[ConversationDomain]:
        """Obtiene una conversación por su ID."""
        pass

    @abstractmethod
    def obtener_estado_conversacion(self, conversation_id: str) -> ConversationState:
        """Obtiene root_issue y last_context de una conversación."""
        pass

    @abstractmethod
    def actualizar_estado_conversacion(
        self,
        conversation_id: str,
        root_issue: Optional[str] = None,
        last_context: Optional[str] = None
    ) -> None:
        """Actualiza el estado de seguimiento de la conversación."""
        pass

    @abstractmethod
    def obtener_historial(
        self,
        conversation_id: str,
        limite: int = 8
    ) -> List[dict]:
        """Obtiene el historial de mensajes ordenado cronológicamente."""
        pass

    @abstractmethod
    def agregar_mensaje(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        rol: str,
        mensaje: str
    ) -> None:
        """Agrega un mensaje al historial y asegura la conversación."""
        pass

    @abstractmethod
    def obtener_conversaciones(self, user_name: str) -> List[ConversationDomain]:
        """Obtiene las conversaciones de un usuario ordenadas por última actualización."""
        pass

    @abstractmethod
    def eliminar_conversacion(self, conversation_id: str) -> None:
        """Elimina una conversación y sus mensajes en cascada."""
        pass
