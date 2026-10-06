from fastapi import APIRouter, Request

from app.models.chat_request import ChatRequest
from app.services.rag_service import RagService

import hashlib


router = APIRouter()

rag_service = RagService()


# ============================================================
# CHAT WEB / API
# ============================================================

@router.post("/chat")
async def chat(request: ChatRequest):

    # Si no viene conversation_id, usamos uno temporal
    conversation_id = (
        request.conversation_id
        or f"web_{request.user_id or request.user_name}"
    )

    user_id = (
        request.user_id
        or request.user_name
    )

    respuesta = rag_service.responder(
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=request.user_name,
        pregunta=request.question
    )

    return {
        "status": "success",
        "answer": respuesta,
        "conversation_id": conversation_id
    }


# ============================================================
# GOOGLE CHAT
# ============================================================

@router.post("/google-chat")
async def google_chat(request: Request):

    data = await request.json()

    print("=" * 60)
    print("MENSAJE RECIBIDO DESDE GOOGLE CHAT")
    print("=" * 60)

    # --------------------------------------------------------
    # ESTRUCTURA REAL DE GOOGLE CHAT
    # --------------------------------------------------------

    chat = data.get("chat", {})

    user = chat.get("user", {})

    message_payload = chat.get(
        "messagePayload",
        {}
    )

    message = message_payload.get(
        "message",
        {}
    )

    # --------------------------------------------------------
    # USUARIO
    # --------------------------------------------------------

    user_name = (
        user.get("displayName")
        or user.get("name")
        or "Usuario Google Chat"
    )

    user_id = (
        user.get("name")
        or user_name
    )

    # --------------------------------------------------------
    # PREGUNTA
    # --------------------------------------------------------

    pregunta = (
        message.get("argumentText")
        or message.get("text")
        or ""
    ).strip()

    # --------------------------------------------------------
    # SPACE / CONVERSACIÓN
    # --------------------------------------------------------

    space = message_payload.get(
        "space",
        {}
    )

    space_name = space.get(
        "name",
        ""
    )

    space_type = space.get(
        "type",
        ""
    )

    # --------------------------------------------------------
    # THREAD
    # --------------------------------------------------------

    thread = message.get(
        "thread",
        {}
    )

    thread_name = thread.get(
        "name",
        ""
    )

    # --------------------------------------------------------
    # CONVERSATION ID
    # --------------------------------------------------------

    if space_type == "DM" and space_name:

        # En un chat directo usamos el espacio como
        # conversación permanente.

        hash_space = hashlib.sha256(
            space_name.encode("utf-8")
        ).hexdigest()

        conversation_id = (
            "gchat_dm_"
            + hash_space[:40]
        )

    else:

        # En espacios con múltiples conversaciones,
        # utilizamos el thread como conversación.

        hash_thread = hashlib.sha256(
            thread_name.encode("utf-8")
        ).hexdigest()

        conversation_id = (
            "gchat_"
            + hash_thread[:44]
        )

    # --------------------------------------------------------
    # DEBUG
    # --------------------------------------------------------

    print(f"Usuario: {user_name}")
    print(f"User ID: {user_id}")
    print(f"Pregunta: {pregunta}")
    print(f"Space: {space_name}")
    print(f"Space type: {space_type}")
    print(f"Thread: {thread_name}")
    print(f"Conversation ID: {conversation_id}")

    # --------------------------------------------------------
    # VALIDAR PREGUNTA
    # --------------------------------------------------------

    if not pregunta:

        return {
            "text": "No recibí ninguna pregunta."
        }

    # --------------------------------------------------------
    # RAG + MYSQL + GEMINI
    # --------------------------------------------------------

    respuesta = rag_service.responder(
    conversation_id=conversation_id,
    user_id=user_id,
    user_name=user_name,
    pregunta=pregunta
)

    print("Respuesta generada:")
    print(respuesta)

    print("=" * 60)

    return {
        "hostAppDataAction": {
            "chatDataAction": {
                "createMessageAction": {
                    "message": {
                        "text": respuesta
                }
            }
        }
    }
}