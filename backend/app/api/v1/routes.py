import logging
from fastapi import APIRouter, BackgroundTasks, Depends
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
    background_tasks: BackgroundTasks,
    chat_service: GoogleChatService = Depends(get_google_chat_service),
    rag_service: RagService = Depends(get_rag_service),
    conversation_repo: IConversationRepository = Depends(get_conversation_repository)
):
    """Endpoint delegador del webhook de Google Chat validado mediante DTO."""
    space_name, space_type = event.get_space()
    texto = event.get_text_content()
    user = event.get_user_display_name()
    logger.warning(
        "[WEBHOOK DETECCIÓN] user='%s', space='%s', texto='%s'",
        user, space_name, texto
    )

    # 1. Evento de Instalación / Adición al espacio (ADDED_TO_SPACE):
    # Responder de forma síncrona en el HTTP 200 para evitar el error 403 de la REST API al instalar.
    if event.is_added_to_space():
        thread_name = event.get_thread_name()
        target_thread = thread_name if event.is_in_thread() else None

        msg_bienvenida = (
            f"¡Hola, {user}! 👋 Soy **SmartSupport**, Asistente Técnico de TI Nivel 1.\n\n"
            "Estoy aquí para ayudarte con guías paso a paso e incidentes en sistemas como "
            "VPN (GlobalProtect/FortiClient), WPASS, Citrix, SAP, cuentas y soporte HWI.\n\n"
            "¿En qué problema o requerimiento te puedo ayudar hoy?"
        )

        payload_sync = {"text": msg_bienvenida}
        if target_thread:
            payload_sync["thread"] = {"name": target_thread}
        return payload_sync

    # 2. Delegar procesamiento completo de consultas y RAG a segundo plano
    background_tasks.add_task(
        chat_service.procesar_evento_con_reintentos,
        event=event,
        rag_service=rag_service,
        conversation_repo=conversation_repo
    )

    # Retornar JSON vacío {} con HTTP 200 le confirma a Google Chat la recepción del webhook
    return {}