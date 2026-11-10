import logging
from fastapi import APIRouter, Depends, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_google_chat_service, verify_chat_signature
from app.core.database import SessionLocal
from app.api.dependencies import build_conversation_repository, build_rag_service
from app.core.messages import MENSAJE_ERROR_RESCATE
from app.schemas.google_chat import GoogleChatEventDTO

logger = logging.getLogger(__name__)
router = APIRouter()


async def ejecutar_en_background(event: GoogleChatEventDTO):
    db = SessionLocal()
    try:
        conversation_repo = build_conversation_repository(db)
        rag_service = build_rag_service(conversation_repo=conversation_repo)
        chat_service = get_google_chat_service()

        await chat_service.procesar_evento_chat(
            event=event,
            rag_service=rag_service,
            conversation_repo=conversation_repo
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.critical("[BACKGROUND ERROR] Excepción no controlada procesando evento: %s", exc, exc_info=True)
        chat_service = get_google_chat_service()
        await chat_service.enviar_mensaje_rescate(event, MENSAJE_ERROR_RESCATE)
    finally:
        db.close()


@router.post("/google-chat")
async def google_chat(
    request: Request,
    event: GoogleChatEventDTO,
    background_tasks: BackgroundTasks,
    token_payload: dict = Depends(verify_chat_signature)
) -> JSONResponse:
    space_name, _ = event.get_space()
    user_name = event.get_user_display_name()
    es_boton = event.is_button_click()

    logger.info(
        "[WEBHOOK RECIBIDO] user='%s', space='%s', tipo='%s', boton=%s",
        user_name, space_name, event.type, es_boton
    )

    # Lanzamos el trabajo asíncrono
    background_tasks.add_task(ejecutar_en_background, event)

    if es_boton:
        # RESPUESTA EXIGIDA POR GOOGLE CHAT PARA BOTONES INTERACTIVOS:
        # actionResponse con type NEW_MESSAGE indica a Google Chat que acepte el clic sin error
        # y que el bot enviará la respuesta por la API REST asíncronamente.
        return JSONResponse(
            status_code=200,
            content={
                "actionResponse": {
                    "type": "NEW_MESSAGE"
                }
            }
        )
    else:
        return JSONResponse(status_code=200, content={})