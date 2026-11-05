import base64
import hashlib
import logging
import time
from typing import Any, Dict, Optional
import httpx
from app.core.config import settings
from app.core.security import obtener_token_google_chat
from app.schemas.google_chat import GoogleChatEventDTO
from app.repositories.interfaces.conversation_repository import IConversationRepository

logger = logging.getLogger(__name__)

COMANDOS_RESET = {
    "cambiar tema", "cambiar contexto", "nuevo tema",
    "reiniciar", "reiniciar conversacion", "reiniciar conversación",
    "limpiar chat", "reset", "/reset", "/nuevo"
}


class GoogleChatService:
    """
    Servicio de integración y orquestación para Google Chat:
    - Construcción dinámica de cards y botones interactivos V2 (Sí/No condicionales y Cambiar tema persistente).
    - Envío asíncrono de mensajes y respuestas en hilos/espacios (REST API).
    - Respuesta síncrona en el body HTTP 200 como fallback de alta resiliencia.
    - Gestión precisa de hilos (threads) en DMs vs Spaces.
    - Descarga autenticada de imágenes adjuntas.
    - Procesamiento desacoplado del webhook.
    """

    @staticmethod
    def calcular_conversation_id(space_type: str, space_name: str, thread_name: str, user_id: str) -> str:
        if space_type == "DM" and space_name:
            hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
            return f"gchat_dm_{hash_space[:40]}"
        elif thread_name:
            hash_thread = hashlib.sha256(thread_name.encode("utf-8")).hexdigest()
            return f"gchat_{hash_thread[:44]}"
        elif space_name:
            hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
            return f"gchat_space_{hash_space[:40]}"
        else:
            return f"gchat_user_{user_id}"

    @staticmethod
    def construir_cards_v2(mostrar_sino: bool = True, mostrar_cambiar_tema: bool = True) -> list:
        """
        Construye tarjetas de botones interactivas en base a la necesidad de la respuesta:
        - Si mostrar_sino=True: incluye [✅ Sí], [❌ No] y [🔄 Cambiar tema].
        - Si mostrar_sino=False y mostrar_cambiar_tema=True: incluye ÚNICAMENTE [🔄 Cambiar tema].
        - Si ambos son False: retorna lista vacía.
        """
        botones = []

        if mostrar_sino:
            botones.extend([
                {
                    "text": "✅ Sí",
                    "onClick": {
                        "action": {
                            "function": settings.CHAT_ACTION_URL,
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
                            "function": settings.CHAT_ACTION_URL,
                            "parameters": [
                                {"key": "action", "value": "quick_reply"},
                                {"key": "reply", "value": "No"}
                            ]
                        }
                    }
                }
            ])

        if mostrar_cambiar_tema:
            botones.append({
                "text": "🔄 Cambiar tema",
                "onClick": {
                    "action": {
                        "function": settings.CHAT_ACTION_URL,
                        "parameters": [
                            {"key": "action", "value": "reset"},
                            {"key": "reply", "value": "Cambiar tema"}
                        ]
                    }
                }
            })

        if not botones:
            return []

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
                                        "buttons": botones
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        ]

    async def enviar_mensaje(
        self,
        space_name: str,
        thread_name: Optional[str],
        texto: str,
        mostrar_sino: bool = False,
        mostrar_cambiar_tema: bool = False
    ) -> bool:
        """
        Envía un mensaje a Google Chat vía REST API.
        Si thread_name es provisto, responde dentro de ese hilo.
        Si thread_name es None, publica en el flujo principal del chat.
        """
        token = await obtener_token_google_chat()
        if not token:
            logger.warning("[GOOGLE CHAT] No se envió mensaje vía REST API: token OAuth ausente.")
        if not space_name:
            logger.warning("[GOOGLE CHAT] No se envió mensaje vía REST API: space_name ausente.")
        if not token or not space_name:
            return False

        url = f"https://chat.googleapis.com/v1/{space_name}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload: dict = {"text": texto}
        params: dict = {}

        if thread_name:
            payload["thread"] = {"name": thread_name}

        cards = self.construir_cards_v2(
            mostrar_sino=mostrar_sino,
            mostrar_cambiar_tema=mostrar_cambiar_tema
        )
        if cards:
            payload["cardsV2"] = cards

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload, params=params)
                if resp.status_code == 200:
                    logger.info("[GOOGLE CHAT] Mensaje publicado exitosamente en %s (hilo=%s).", space_name, bool(thread_name))
                    return True
                else:
                    logger.error("[GOOGLE CHAT ERROR] Status %d: %s", resp.status_code, resp.text)
                    return False
        except Exception as error:
            logger.error("[GOOGLE CHAT ERROR] Excepción al enviar mensaje: %s", error)
            return False

    async def descargar_imagen_adjunta(self, event: GoogleChatEventDTO) -> Optional[str]:
        attachments = event.get_attachments()
        if not attachments:
            return None

        token = await obtener_token_google_chat()
        if not token:
            return None

        for adjunto in attachments:
            content_type = adjunto.contentType or ""
            resource_name = ""
            if adjunto.attachmentDataRef and adjunto.attachmentDataRef.resourceName:
                resource_name = adjunto.attachmentDataRef.resourceName
            elif adjunto.name:
                resource_name = adjunto.name

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
                    logger.info("[GOOGLE CHAT] Descargando imagen: %s", resource_name)
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.get(download_url, headers=headers)
                        if response.status_code == 200:
                            raw_b64 = base64.b64encode(response.content).decode("utf-8")
                            logger.info("[GOOGLE CHAT] Imagen descargada y codificada con éxito.")
                            return f"data:{content_type};base64,{raw_b64}"
                except Exception as error:
                    logger.error("[GOOGLE CHAT ERROR] Fallo al descargar imagen: %s", error)

        return None

    async def procesar_evento_chat(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository
    ) -> Dict[str, Any]:
        """
        Orquesta el ciclo de recepción y respuesta para el evento de Google Chat.
        Garantiza una respuesta rápida y resiliencia ante cualquier excepción.
        """
        space_name, space_type = event.get_space()
        thread_name = event.get_thread_name()
        user_name = event.get_user_display_name()
        user_id = event.get_user_id()
        is_dm = event.is_dm()
        is_button = event.is_button_click()
        action_params = event.get_action_parameters()
        invoked_function = event.get_invoked_function()

        is_in_thread = event.is_in_thread()

        # Enrutamiento determinista de hilo:
        # 1. Si el usuario está explícitamente dentro de un hilo secundario, target_thread = thread_name.
        # 2. Si el usuario presionó un botón O está en el chat principal, target_thread = None.
        target_thread = thread_name if is_in_thread else None

        logger.info(
            "[ENRUTAMIENTO HILO] is_button=%s, is_in_thread=%s, is_dm=%s -> target=%s",
            is_button, is_in_thread, is_dm, target_thread or "CHAT_PRINCIPAL"
        )

        conversation_id = self.calcular_conversation_id(
            space_type="DM" if is_dm else space_type,
            space_name=space_name,
            thread_name=target_thread or "",
            user_id=user_id
        )

        is_reset_action = (
            invoked_function in {"reset", "reset_context"}
            or action_params.get("action") in {"reset", "reset_context"}
        )
        pregunta = action_params.get("reply") or action_params.get("value") or event.get_text_content()

        # Caso: Reinicio de conversación / Cambiar tema
        if is_reset_action or (pregunta and pregunta.lower() in COMANDOS_RESET):
            conversation_repo.eliminar_conversacion(conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_reset,
                mostrar_sino=False,
                mostrar_cambiar_tema=False
            )
            if not enviado:
                payload_sync = {"text": msg_reset}
                if target_thread:
                    payload_sync["thread"] = {"name": target_thread}
                return payload_sync
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

        image_base64 = await self.descargar_imagen_adjunta(event)

        # Caso: Sin mensaje ni adjunto
        if not pregunta and not image_base64:
            msg_vacio = "No recibí ninguna pregunta ni imagen adjunta."
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_vacio,
                mostrar_sino=False,
                mostrar_cambiar_tema=True
            )
            if not enviado:
                payload_sync = {"text": msg_vacio}
                if target_thread:
                    payload_sync["thread"] = {"name": target_thread}
                cards = self.construir_cards_v2(mostrar_sino=False, mostrar_cambiar_tema=True)
                if cards:
                    payload_sync["cardsV2"] = cards
                return payload_sync
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

        if not pregunta and image_base64:
            pregunta = "Revisa la imagen adjunta y diagnostica el problema o error mostrado."

        # Procesamiento RAG
        respuesta, mostrar_sino, mostrar_cambiar_tema = await rag_service.responder(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            pregunta=pregunta,
            image_base64=image_base64
        )

        enviado = await self.enviar_mensaje(
            space_name=space_name,
            thread_name=target_thread,
            texto=respuesta,
            mostrar_sino=mostrar_sino,
            mostrar_cambiar_tema=mostrar_cambiar_tema
        )

        # Fallback síncrono: Si no se pudo enviar vía REST API (ej. problema de token o red),
        # retornamos el mensaje en el cuerpo del HTTP 200 respetando el hilo correspondiente.
        if not enviado:
            logger.info("[GOOGLE CHAT] Enviando respuesta de forma síncrona en el body HTTP 200.")
            payload_sync = {"text": respuesta}
            if target_thread:
                payload_sync["thread"] = {"name": target_thread}
            cards = self.construir_cards_v2(
                mostrar_sino=mostrar_sino,
                mostrar_cambiar_tema=mostrar_cambiar_tema
            )
            if cards:
                payload_sync["cardsV2"] = cards
            return payload_sync

        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}
