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
#  Singletons de infraestructura (sin estado por request)              #
# ------------------------------------------------------------------ #
# Se instancian una sola vez al arrancar la app y se reúsan en cada
# request. Son seguros en concurrencia porque no mututan estado.

_vector_repository_instance: IVectorRepository = QdrantVectorRepository()
_llm_service_instance: ILLMService = GeminiLLMService()
_google_chat_service_instance: GoogleChatService = GoogleChatService()


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
    return MySQLConversationRepository(session=db)


def get_vector_repository() -> IVectorRepository:
    """Provee el repositorio vectorial Qdrant (singleton por proceso)."""
    return _vector_repository_instance


def get_llm_service() -> ILLMService:
    """Provee GeminiLLMService (singleton por proceso). Sustituible por cualquier ILLMService."""
    return _llm_service_instance


def get_google_chat_service() -> GoogleChatService:
    """Provee el servicio de integración con Google Chat."""
    return _google_chat_service_instance


def get_rag_service(
    conversation_repo: IConversationRepository = Depends(get_conversation_repository),
    vector_repo: IVectorRepository = Depends(get_vector_repository),
    llm_service: ILLMService = Depends(get_llm_service)
) -> RagService:
    """
    Ensambla RagService con inversión de dependencias total.
    Todos los colaboradores se inyectan como contratos abstractos (DIP).
    """
    return RagService(
        conversation_repo=conversation_repo,
        vector_repo=vector_repo,
        llm_service=llm_service
    )


def get_indexer_service(
    vector_repo: IVectorRepository = Depends(get_vector_repository)
) -> IndexerService:
    """Provee el servicio de indexación documental."""
    return IndexerService(vector_repo=vector_repo)
