import base64
import hashlib
import os
import time
import httpx
from fastapi import APIRouter, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from app.config import (
    CHAT_ACTION_URL,
    SERVICE_ACCOUNT_FILE,
    GOOGLE_CHAT_SCOPES
)
from app.services.rag_service import RagService

router = APIRouter()
rag_service = RagService()

_cached_credentials: service_account.Credentials | None = None


def obtener_token_google_chat() -> str | None:
    """Obtiene o refresca un Bearer Token usando el archivo service_account.json con caché en memoria."""
    global _cached_credentials
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"ADVERTENCIA: No se encontró el archivo '{SERVICE_ACCOUNT_FILE}'.")
        return None
    try:
        if _cached_credentials is None:
            _cached_credentials = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=GOOGLE_CHAT_SCOPES
            )
        if not _cached_credentials.valid:
            _cached_credentials.refresh(GoogleAuthRequest())
        return _cached_credentials.token
    except Exception as e:
        print(f"Error generando token de Google con service_account.json: {e}")
        return None


COMANDOS_RESET = {
    "cambiar tema", "cambiar contexto", "nuevo tema",
    "reiniciar", "reiniciar conversacion", "reiniciar conversación",
    "limpiar chat", "reset", "/reset", "/nuevo"
}


def construir_cards_v2() -> list:
    """Genera las tarjetas con botones compatibles con Google Chat."""
    unique_card_id = f"actions_{int(time.time() * 1000)}"
    return [
        {
            "cardId": unique_card_id,
            "card": {
                "sections": [
                    {
                        "widgets": [
                            {
                                "buttonList": {
                                    "buttons": [
                                        {
                                            "text": "✅ Sí",
                                            "onClick": {
                                                "action": {
                                                    "function": CHAT_ACTION_URL,
                                                    "parameters": [
                                                        {"key": "action", "value": "quick_reply"},
                                                        {"key": "reply", "value": "Sí"}
                                                    ]
                                                }
                                            }
                                        },
                                        {
                                            "text": "❌ No",
                                            "onClick": {
                                                "action": {
                                                    "function": CHAT_ACTION_URL,
                                                    "parameters": [
                                                        {"key": "action", "value": "quick_reply"},
                                                        {"key": "reply", "value": "No"}
                                                    ]
                                                }
                                            }
                                        },
                                        {
                                            "text": "🔄 Cambiar tema",
                                            "onClick": {
                                                "action": {
                                                    "function": CHAT_ACTION_URL,
                                                    "parameters": [
                                                        {"key": "action", "value": "reset"},
                                                        {"key": "reply", "value": "Cambiar tema"}
                                                    ]
                                                }
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }
    ]


async def enviar_mensaje_google_chat(
    space_name: str,
    space_type: str,
    thread_name: str,
    texto: str,
    token: str,
    mostrar_botones: bool = True
) -> bool:
    """Publica directamente el mensaje vía API REST.
    En chats directos (DM) omite 'thread' para evitar crear hilos separados.
    """
    url = f"https://chat.googleapis.com/v1/{space_name}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"text": texto}
    params = {}

    # Solo en espacios grupales con hilos se asocia thread
    if space_type != "DM" and thread_name:
        payload["thread"] = {"name": thread_name}
        params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

    if mostrar_botones:
        payload["cardsV2"] = construir_cards_v2()

    try:
        print(f"[GOOGLE CHAT API] Publicando mensaje en {space_name}...")
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=payload, params=params)
            print(f"[GOOGLE CHAT API] Status: {resp.status_code}")
            if resp.status_code == 200:
                print("[GOOGLE CHAT API] Mensaje y botones publicados exitosamente.")
                return True
            else:
                print(f"[GOOGLE CHAT API ERROR] Detalle: {resp.text}")
                return False
    except Exception as error:
        print(f"[GOOGLE CHAT API ERROR] Excepción al enviar mensaje: {error}")
        return False


# ============================================================
# GOOGLE CHAT
# ============================================================

@router.post("/google-chat")
async def google_chat(request: Request):
    data = await request.json()

    print("=" * 60)
    print("MENSAJE RECIBIDO DESDE GOOGLE CHAT")
    print("=" * 60)

    chat = data.get("chat", {})
    button_clicked_payload = (
        chat.get("buttonClickedPayload")
        or data.get("buttonClickedPayload")
        or {}
    )
    message_payload = (
        chat.get("messagePayload")
        or data.get("messagePayload")
        or {}
    )

    common_event = data.get("commonEventObject") or {}
    action_event = chat.get("actionEvent") or data.get("action") or {}

    invoked_function = (
        common_event.get("invokedFunction")
        or action_event.get("function")
        or action_event.get("actionMethodName")
        or ""
    )

    action_params = {}
    raw_params = common_event.get("parameters") or action_event.get("parameters") or {}
    if isinstance(raw_params, dict):
        action_params = raw_params
    elif isinstance(raw_params, list):
        for p in raw_params:
            if isinstance(p, dict) and "key" in p:
                action_params[p["key"]] = p.get("value")

    es_click_boton = bool(
        button_clicked_payload
        or data.get("type") == "CARD_CLICKED"
        or invoked_function
        or action_params
    )

    space = (
        chat.get("space")
        or button_clicked_payload.get("space")
        or message_payload.get("space")
        or data.get("space")
        or {}
    )
    space_name = space.get("name", "")
    space_type = space.get("type", "")

    message = (
        message_payload.get("message")
        or button_clicked_payload.get("message")
        or data.get("message")
        or {}
    )

    thread = message.get("thread") or data.get("thread") or {}
    thread_name = thread.get("name", "")

    user = chat.get("user") or data.get("user") or message.get("sender") or {}
    user_name = (
        user.get("displayName")
        or user.get("name")
        or "Usuario Google Chat"
    )
    user_id = user.get("name") or user_name

    # En chats directos, conversation_id se basa en el espacio completo para no fragmentar
    if space_type == "DM" and space_name:
        hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
        conversation_id = "gchat_dm_" + hash_space[:40]
    elif thread_name:
        hash_thread = hashlib.sha256(thread_name.encode("utf-8")).hexdigest()
        conversation_id = "gchat_" + hash_thread[:44]
    elif space_name:
        hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
        conversation_id = "gchat_space_" + hash_space[:40]
    else:
        conversation_id = f"gchat_user_{user_id}"

    token = obtener_token_google_chat()

    # --------------------------------------------------------
    # GESTIÓN DE ACCIONES DE BOTONES
    # --------------------------------------------------------
    if es_click_boton:
        print(f"Evento de botón detectado. Función: {invoked_function}, Parámetros: {action_params}")

        # Botón "Cambiar tema"
        if (invoked_function == "reset_context"or action_params.get("action") in {"reset", "reset_context"}):
            print(f"Botón 'Cambiar tema' presionado para {conversation_id}.")
            rag_service.conversation.eliminar_conversacion(conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            if token and space_name:
                await enviar_mensaje_google_chat(
                    space_name=space_name,
                    space_type=space_type,
                    thread_name=thread_name,
                    texto=msg_reset,
                    token=token,
                    mostrar_botones=False
                )
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}}

        # Botones de respuesta rápida (Sí / No)
        reply_val = action_params.get("reply") or action_params.get("value") or ""
        pregunta = str(reply_val).strip()
        print(f"Pregunta recibida desde botón: '{pregunta}'")
    else:
        pregunta = (
            message.get("argumentText")
            or message.get("text")
            or ""
        ).strip()

        # Comando de texto para reiniciar
        if pregunta.lower() in COMANDOS_RESET:
            print(f"Comando de reinicio detectado por texto para {conversation_id}.")
            rag_service.conversation.eliminar_conversacion(conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            if token and space_name:
                await enviar_mensaje_google_chat(
                    space_name=space_name,
                    space_type=space_type,
                    thread_name=thread_name,
                    texto=msg_reset,
                    token=token,
                    mostrar_botones=False
                )
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if es_click_boton else {}

    # --------------------------------------------------------
    # DESCARGA DE IMÁGENES AUTENTICADA
    # --------------------------------------------------------
    image_base64 = None
    attachments = message.get("attachment") or message.get("attachments") or []

    if attachments and token:
        print(f"Se encontraron {len(attachments)} adjunto(s).")
        for adjunto in attachments:
            content_type = adjunto.get("contentType", "")
            data_ref = adjunto.get("attachmentDataRef") or {}
            resource_name = data_ref.get("resourceName") or adjunto.get("name") or ""

            is_image = (
                content_type.startswith("image/")
                or any(resource_name.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"])
            )

            if is_image and resource_name:
                if not content_type:
                    content_type = "image/jpeg"

                download_url = f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media"
                headers = {"Authorization": f"Bearer {token}"}

                try:
                    print(f"Descargando imagen vía Chat API: {resource_name}")
                    async with httpx.AsyncClient(timeout=25.0) as client:
                        response = await client.get(download_url, headers=headers)
                        if response.status_code == 200:
                            raw_b64 = base64.b64encode(response.content).decode("utf-8")
                            image_base64 = f"data:{content_type};base64,{raw_b64}"
                            print("Imagen descargada con éxito y convertida a Base64.")
                            break
                        else:
                            print(f"Error Chat API al descargar imagen: {response.status_code} - {response.text}")
                except Exception as error:
                    print(f"Excepción al descargar imagen vía API: {error}")

    print(f"Usuario: {user_name}")
    print(f"Pregunta: {pregunta}")
    print(f"Tiene Imagen: {'Sí' if image_base64 else 'No'}")
    print(f"Es Clic Botón: {'Sí' if es_click_boton else 'No'}")
    print(f"Space: {space_name}")
    print(f"Space type: {space_type}")

    # Validación de contenido
    if not pregunta and not image_base64:
        msg_vacio = "No recibí ninguna pregunta ni imagen adjunta."
        if token and space_name:
            await enviar_mensaje_google_chat(
                space_name=space_name,
                space_type=space_type,
                thread_name=thread_name,
                texto=msg_vacio,
                token=token,
                mostrar_botones=False
            )
        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if es_click_boton else {}

    if not pregunta and image_base64:
        pregunta = "Revisa la imagen adjunta y diagnostica el problema o error mostrado."

    # --------------------------------------------------------
    # RAG + MYSQL + GEMINI
    # --------------------------------------------------------
    respuesta = rag_service.responder(
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=user_name,
        pregunta=pregunta,
        image_base64=image_base64
    )

    print("Respuesta generada:")
    print(respuesta)
    print("=" * 60)

    # --------------------------------------------------------
    # PUBLICACIÓN DIRECTA EN GOOGLE CHAT
    # --------------------------------------------------------
    if token and space_name:
        await enviar_mensaje_google_chat(
            space_name=space_name,
            space_type=space_type,
            thread_name=thread_name,
            texto=respuesta,
            token=token,
            mostrar_botones=True
        )

    # Si provino de un botón, confirmar acción; si fue texto/imagen, respuesta vacía
    if es_click_boton:
        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}}

    return {}