import asyncio
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
    - Construcción de cards y botones interactivos V2.
    - Envío asíncrono de mensajes y respuestas en hilos/espacios (REST API).
    - Respuesta síncrona en el body HTTP 200 como fallback de alta resiliencia.
    - Gestión precisa de hilos (threads) en DMs vs Spaces.
    - Descarga autenticada de imágenes adjuntas vía REST API v1.
    - Procesamiento desacoplado con reintentos y tolerancia a latencia/fallos.
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
    def construir_cards_v2() -> list:
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
                                            },
                                            {
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

    async def enviar_mensaje(
        self,
        space_name: str,
        thread_name: Optional[str],
        texto: str,
        mostrar_botones: bool = True
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

        if mostrar_botones:
            payload["cardsV2"] = self.construir_cards_v2()

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
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
            logger.info("[GOOGLE CHAT] No se encontraron adjuntos en el evento.")
            return None

        token = await obtener_token_google_chat()
        if not token:
            logger.error("[GOOGLE CHAT ERROR] No se pudo obtener el token OAuth2 para descargar la imagen.")
            return None

        logger.info("[GOOGLE CHAT] Se detectaron %d adjunto(s) en el evento.", len(attachments))

        for adjunto in attachments:
            content_type = adjunto.contentType or ""
            content_name = getattr(adjunto, "contentName", None) or adjunto.name or ""
            
            # Extraer la ruta del recurso para la API REST v1
            resource_path = None
            if adjunto.attachmentDataRef and adjunto.attachmentDataRef.resourceName:
                resource_path = adjunto.attachmentDataRef.resourceName
            elif adjunto.name:
                resource_path = adjunto.name

            # Fallback: construir resource_path usando el ID del mensaje padre
            if not resource_path:
                msg_name = event.get_message_name()
                if msg_name and "spaces/" in msg_name:
                    att_id = adjunto.name or "attachment"
                    if "attachments/" in att_id:
                        att_id = att_id.split("attachments/", 1)[1]
                    resource_path = f"{msg_name}/attachments/{att_id}"

            if not resource_path:
                logger.warning("[GOOGLE CHAT ADVERTENCIA] Omitiendo adjunto sin ruta de recurso válida.")
                continue

            # Validar si el adjunto corresponde a una imagen
            is_image = (
                not content_type
                or content_type.startswith("image/")
                or content_type == "application/octet-stream"
                or any(ext in content_name.lower() for ext in [".png", ".jpg", ".jpeg", ".webp"])
                or any(ext in resource_path.lower() for ext in [".png", ".jpg", ".jpeg", ".webp"])
            )

            if not is_image:
                logger.info("[GOOGLE CHAT] Adjunto omitido por no ser identificado como imagen.")
                continue

            if not content_type or content_type == "application/octet-stream":
                content_type = "image/jpeg"

            # Normalizar el prefijo 'media/' para evitar URLs duplicadas o malformadas
            clean_res = resource_path.lstrip("/")
            if clean_res.startswith("media/"):
                clean_res = clean_res[6:]

            # Endpoint único y definitivo para Service Accounts en Google Chat API v1
            download_url = f"https://chat.googleapis.com/v1/media/{clean_res}?alt=media"
            headers = {"Authorization": f"Bearer {token}"}

            try:
                logger.info("[GOOGLE CHAT] Descargando imagen vía API v1: %s", download_url)
                async with httpx.AsyncClient(timeout=25.0) as client:
                    response = await client.get(download_url, headers=headers)
                    if response.status_code == 200:
                        raw_b64 = base64.b64encode(response.content).decode("utf-8")
                        logger.info(
                            "[GOOGLE CHAT] Imagen descargada y codificada con éxito (%d bytes).",
                            len(response.content)
                        )
                        return f"data:{content_type};base64,{raw_b64}"
                    else:
                        logger.warning(
                            "[GOOGLE CHAT ADVERTENCIA] Status %d desde API v1 (%s): %s",
                            response.status_code, download_url, response.text[:200]
                        )
            except Exception as error:
                logger.error("[GOOGLE CHAT ERROR] Excepción al descargar desde API v1 (%s): %s", download_url, error)

        return None

    async def procesar_evento_chat(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository
    ) -> Dict[str, Any]:
        """
        Orquesta el ciclo de recepción y respuesta para el evento de Google Chat.
        """
        space_name, space_type = event.get_space()
        thread_name = event.get_thread_name()
        user_name = event.get_user_display_name()
        user_id = event.get_user_id()
        is_dm = event.is_dm()
        is_thread_reply = event.is_thread_reply()
        is_button = event.is_button_click()
        action_params = event.get_action_parameters()
        invoked_function = event.get_invoked_function()

        is_in_thread = event.is_in_thread()

        # Enrutamiento determinista de hilo:
        target_thread = thread_name if is_in_thread else None

        logger.warning(
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

        if is_reset_action or pregunta.lower() in COMANDOS_RESET:
            await asyncio.to_thread(conversation_repo.eliminar_conversacion, conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_reset,
                mostrar_botones=False
            )
            if not enviado:
                payload_sync = {"text": msg_reset}
                if target_thread:
                    payload_sync["thread"] = {"name": target_thread}
                return payload_sync
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

        image_base64 = await self.descargar_imagen_adjunta(event)

        if not pregunta and not image_base64:
            msg_vacio = "No recibí ninguna pregunta ni imagen adjunta."
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_vacio,
                mostrar_botones=False
            )
            if not enviado:
                payload_sync = {"text": msg_vacio}
                if target_thread:
                    payload_sync["thread"] = {"name": target_thread}
                return payload_sync
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

        if not pregunta and image_base64:
            pregunta = "Revisa la imagen adjunta y diagnostica el problema o error mostrado."

        respuesta, mostrar_botones = await rag_service.responder(
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
            mostrar_botones=mostrar_botones
        )

        if not enviado:
            logger.info("[GOOGLE CHAT] Enviando respuesta de forma síncrona en el body HTTP 200.")
            payload_sync: dict = {"text": respuesta}
            if target_thread:
                payload_sync["thread"] = {"name": target_thread}
            if mostrar_botones:
                payload_sync["cardsV2"] = self.construir_cards_v2()
            return payload_sync

        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

    async def procesar_evento_con_reintentos(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository,
        max_reintentos: int = 3
    ) -> None:
        """
        Ejecuta el procesamiento del evento en segundo plano con lógica de reintentos
        y garantía de respuesta al usuario mediante REST API.
        """
        space_name, _ = event.get_space()
        thread_name = event.get_thread_name()
        is_in_thread = event.is_in_thread()
        target_thread = thread_name if is_in_thread else None

        intentos = 0
        exito = False

        while intentos < max_reintentos and not exito:
            intentos += 1
            try:
                logger.info("[RESILIENCIA] Procesando evento (intento %d/%d)...", intentos, max_reintentos)
                await self.procesar_evento_chat(
                    event=event,
                    rag_service=rag_service,
                    conversation_repo=conversation_repo
                )
                exito = True
            except Exception as error:
                logger.error(
                    "[RESILIENCIA ERROR] Fallo en intento %d/%d al procesar evento: %s",
                    intentos, max_reintentos, error, exc_info=True
                )
                if intentos < max_reintentos:
                    await asyncio.sleep(1.5 * intentos)

        if not exito and space_name:
            msg_error = (
                "⚠️ *Inconveniente temporal de conexión*\n\n"
                "Tuve un problema procesando tu solicitud debido a una alta latencia en los servicios. "
                "Por favor, intenta enviar tu consulta de nuevo."
            )
            logger.warning("[RESILIENCIA] Enviando respuesta de emergencia a %s", space_name)
            await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_error,
                mostrar_botones=False
            )