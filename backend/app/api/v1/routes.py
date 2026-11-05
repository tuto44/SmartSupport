import asyncio
import logging
from fastapi import APIRouter, Depends
from app.api.dependencies import (
    get_google_chat_service,
    get_rag_service,
    get_conversation_repository
)
from app.core.config import settings
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
    """
    Endpoint delegador del webhook de Google Chat validado mediante DTO.
    Incorpora blindaje contra timeouts y respuesta de rescate HTTP 200 siempre.
    """
    space_name, _ = event.get_space()
    texto = event.get_text_content()
    user = event.get_user_display_name()
    thread_name = event.get_thread_name() if event.is_in_thread() else None

    logger.info(
        "[WEBHOOK DETECCIÓN] user='%s', space='%s', texto='%s'",
        user, space_name, texto
    )

    try:
        # Control estricto de timeout antes de que Google Chat aborte la conexión
        return await asyncio.wait_for(
            chat_service.procesar_evento_chat(
                event=event,
                rag_service=rag_service,
                conversation_repo=conversation_repo
            ),
            timeout=settings.REQUEST_TIMEOUT_SECONDS
        )

    except asyncio.TimeoutError:
        logger.error(
            "[TIMEOUT GOOGLE CHAT] Excedido límite de %s segundos para el usuario '%s'.",
            settings.REQUEST_TIMEOUT_SECONDS, user
        )
        msg_timeout = (
            "⏳ *Tu solicitud está tomando un poco más de tiempo de lo esperado.*\n\n"
            "El sistema experimenta una demora temporal con el servicio de IA o la base de conocimientos. "
            "Por favor, intenta enviar tu mensaje nuevamente o presiona **Cambiar tema** para reiniciar la consulta."
        )
        # Intentar publicar por REST API o retornar síncrono
        enviado = await chat_service.enviar_mensaje(
            space_name=space_name,
            thread_name=thread_name,
            texto=msg_timeout,
            mostrar_sino=False,
            mostrar_cambiar_tema=True
        )
        if not enviado:
            payload = {"text": msg_timeout}
            if thread_name:
                payload["thread"] = {"name": thread_name}
            cards = chat_service.construir_cards_v2(mostrar_sino=False, mostrar_cambiar_tema=True)
            if cards:
                payload["cardsV2"] = cards
            return payload
        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if event.is_button_click() else {}

    except Exception as exc:
        logger.critical(
            "[WEBHOOK ERROR INESPERADO] Error procesando mensaje de Google Chat: %s",
            exc,
            exc_info=True
        )
        msg_error = (
            "⚠️ *Ocurrió un error temporal al procesar tu solicitud.*\n\n"
            "Por favor, intenta de nuevo en unos momentos o presiona **Cambiar tema** para restablecer el contexto."
        )
        try:
            enviado = await chat_service.enviar_mensaje(
                space_name=space_name,
                thread_name=thread_name,
                texto=msg_error,
                mostrar_sino=False,
                mostrar_cambiar_tema=True
            )
            if not enviado:
                payload = {"text": msg_error}
                if thread_name:
                    payload["thread"] = {"name": thread_name}
                cards = chat_service.construir_cards_v2(mostrar_sino=False, mostrar_cambiar_tema=True)
                if cards:
                    payload["cardsV2"] = cards
                return payload
        except Exception as send_err:
            logger.error("[WEBHOOK ERROR RESCATE] Falló envío de mensaje de rescate: %s", send_err)
            return {"text": msg_error}

        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if event.is_button_click() else {}
