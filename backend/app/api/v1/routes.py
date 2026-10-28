import logging
from fastapi import APIRouter, Depends
from app.api.dependencies import (
    get_google_chat_service,
    get_rag_service,
    get_conversation_repository
)
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.schemas.google_chat import GoogleChatEventDTO
from app.services.google_chat_service import GoogleChatService
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/google-chat")
async def google_chat(
    event: GoogleChatEventDTO,
    chat_service: GoogleChatService = Depends(get_google_chat_service),
    rag_service: RagService = Depends(get_rag_service),
    conversation_repo: IConversationRepository = Depends(get_conversation_repository)
):
    """Endpoint delegador del webhook de Google Chat validado mediante DTO."""
    return await chat_service.procesar_evento_chat(
        event=event,
        rag_service=rag_service,
        conversation_repo=conversation_repo
    )
