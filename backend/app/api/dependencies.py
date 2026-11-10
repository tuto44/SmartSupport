from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.services.interfaces.llm_service import ILLMService
from app.repositories.implementations.mysql_conversation_repository import MySQLConversationRepository
from app.repositories.implementations.qdrant_vector_repository import QdrantVectorRepository
from app.services.implementations.gemini_llm_service import GeminiLLMService
from app.services.rag_service import RagService
from app.services.google_chat_service import GoogleChatService
from app.services.indexer_service import IndexerService

# ------------------------------------------------------------------ #
#  Singletons de infraestructura (perezosos / lazy)                    #
# ------------------------------------------------------------------ #
_vector_repository_instance: IVectorRepository | None = None
_llm_service_instance: ILLMService | None = None
_google_chat_service_instance: GoogleChatService | None = None


# ------------------------------------------------------------------ #
#  Factories puras (usables fuera del ciclo request/response)          #
# ------------------------------------------------------------------ #

def build_conversation_repository(db: Session) -> IConversationRepository:
    """Construye el repositorio de conversaciones sobre una sesión dada."""
    return MySQLConversationRepository(session=db)


def build_rag_service(
    conversation_repo: IConversationRepository,
    vector_repo: IVectorRepository | None = None,
    llm_service: ILLMService | None = None
) -> RagService:
    """
    Ensambla RagService con inversión de dependencias total.

    Los colaboradores de infraestructura se resuelven como singletons lazy
    cuando no se inyectan explícitamente (útil en tareas de background).
    """
    return RagService(
        conversation_repo=conversation_repo,
        vector_repo=vector_repo or get_vector_repository(),
        llm_service=llm_service or get_llm_service()
    )


# ------------------------------------------------------------------ #
#  Proveedores de Dependencias (FastAPI Depends)                       #
# ------------------------------------------------------------------ #

def get_conversation_repository(
    db: Session = Depends(get_db)
) -> IConversationRepository:
    """
    Provee MySQLConversationRepository ligado a la sesión activa del request.
    El ciclo de vida de la sesión (commit/rollback) lo gestiona get_db().
    """
    return build_conversation_repository(db)


def get_vector_repository() -> IVectorRepository:
    """Provee el repositorio vectorial Qdrant aplicando lazy singleton."""
    global _vector_repository_instance
    if _vector_repository_instance is None:
        _vector_repository_instance = QdrantVectorRepository()
    return _vector_repository_instance


def get_llm_service() -> ILLMService:
    """Provee GeminiLLMService aplicando lazy singleton."""
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = GeminiLLMService()
    return _llm_service_instance


def get_google_chat_service() -> GoogleChatService:
    """Provee GoogleChatService aplicando lazy singleton."""
    global _google_chat_service_instance
    if _google_chat_service_instance is None:
        _google_chat_service_instance = GoogleChatService()
    return _google_chat_service_instance


def get_rag_service(
    conversation_repo: IConversationRepository = Depends(get_conversation_repository),
    vector_repo: IVectorRepository = Depends(get_vector_repository),
    llm_service: ILLMService = Depends(get_llm_service)
) -> RagService:
    """Ensambla RagService para el ciclo request/response de FastAPI."""
    return build_rag_service(
        conversation_repo=conversation_repo,
        vector_repo=vector_repo,
        llm_service=llm_service
    )


def get_indexer_service(
    vector_repo: IVectorRepository = Depends(get_vector_repository)
) -> IndexerService:
    """Provee el servicio de indexación documental."""
    return IndexerService(vector_repo=vector_repo)
