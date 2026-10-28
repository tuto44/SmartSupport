from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.repositories.implementations.mysql_conversation_repository import MySQLConversationRepository
from app.repositories.implementations.qdrant_vector_repository import QdrantVectorRepository
from app.services.rag_service import RagService
from app.services.google_chat_service import GoogleChatService
from app.services.indexer_service import IndexerService

_vector_repository_instance = QdrantVectorRepository()
_google_chat_service_instance = GoogleChatService()


def get_conversation_repository(
    db: Session = Depends(get_db)
) -> IConversationRepository:
    """Provee el repositorio de conversaciones dentro del ciclo transaccional de la sesión."""
    return MySQLConversationRepository(session=db)


def get_vector_repository() -> IVectorRepository:
    """Provee el repositorio de vectores."""
    return _vector_repository_instance


def get_google_chat_service() -> GoogleChatService:
    """Provee el servicio de integración con Google Chat."""
    return _google_chat_service_instance


def get_rag_service(
    conversation_repo: IConversationRepository = Depends(get_conversation_repository),
    vector_repo: IVectorRepository = Depends(get_vector_repository)
) -> RagService:
    """Provee el servicio RAG ensamblado con inversión de dependencias."""
    return RagService(
        conversation_repo=conversation_repo,
        vector_repo=vector_repo
    )


def get_indexer_service(
    vector_repo: IVectorRepository = Depends(get_vector_repository)
) -> IndexerService:
    """Provee el servicio de indexación documental."""
    return IndexerService(vector_repo=vector_repo)
