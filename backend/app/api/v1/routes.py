import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    get_conversation_repository,
    get_google_chat_service,
    get_rag_service
)
from app.core.config import settings
from app.core.messages import MENSAJE_ERROR_RESCATE, MENSAJE_PROCESANDO
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
) -> JSONResponse:
    """
    Webhook principal de Google Chat.

    Procesa la interacción de forma controlada y publica el mensaje mediante la API REST
    oficial de Google Chat. Responde con HTTP 200 y el actionResponse adecuado para botones.
    """
    space_name, _ = event.get_space()
    user_name = event.get_user_display_name()
    es_boton = event.is_button_click()

    logger.info(
        "[WEBHOOK RECIBIDO] user='%s', space='%s', tipo='%s', boton=%s",
        user_name, space_name, event.type, es_boton
    )

    try:
        resultado = await asyncio.wait_for(
            chat_service.procesar_evento_chat(
                event=event,
                rag_service=rag_service,
                conversation_repo=conversation_repo
            ),
            timeout=settings.REQUEST_TIMEOUT_SECONDS
        )
        return JSONResponse(status_code=200, content=resultado)

    except asyncio.TimeoutError:
        logger.error(
            "[WEBHOOK TIMEOUT] Tiempo límite excedido (%.1fs) para user='%s'.",
            settings.REQUEST_TIMEOUT_SECONDS, user_name
        )
        await chat_service.enviar_mensaje_rescate(event, MENSAJE_PROCESANDO)
        contenido = {"actionResponse": {"type": "NEW_MESSAGE"}} if es_boton else {}
        return JSONResponse(status_code=200, content=contenido)

    except Exception as exc:
        logger.critical(
            "[WEBHOOK ERROR] Excepción no controlada procesando evento de Google Chat: %s",
            exc, exc_info=True
        )
        await chat_service.enviar_mensaje_rescate(event, MENSAJE_ERROR_RESCATE)
        contenido = {"actionResponse": {"type": "NEW_MESSAGE"}} if es_boton else {}
        return JSONResponse(status_code=200, content=contenido)
