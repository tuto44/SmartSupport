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
    @staticmethod
    def _hash_usuario(user_id: str) -> str:
        base = (user_id or "anonimo").encode("utf-8")
        return hashlib.sha256(base).hexdigest()[:12]

    @staticmethod
    def calcular_conversation_id(space_type: str, space_name: str, thread_name: str, user_id: str) -> str:
        sufijo_usuario = GoogleChatService._hash_usuario(user_id)
        if space_type in {"DM", "DIRECT_MESSAGE"} and space_name:
            hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
            return f"gchat_dm_{hash_space[:40]}"
        elif thread_name:
            hash_thread = hashlib.sha256(thread_name.encode("utf-8")).hexdigest()
            return f"gchat_thread_{hash_thread[:32]}_user_{sufijo_usuario}"
        elif space_name:
            hash_space = hashlib.sha256(space_name.encode("utf-8")).hexdigest()
            return f"gchat_space_{hash_space[:32]}_user_{sufijo_usuario}"
        else:
            return f"gchat_user_{sufijo_usuario}"

    @staticmethod
    def construir_cards_v2(tipo_botones: str = "NONE") -> list:
        tipo = (tipo_botones or "NONE").upper()
        botones = []

        if tipo == "ALL":
            botones.extend([
                {
                    "text": "✅ Sí",
                    "onClick": {
                        "action": {
                            "actionMethodName": "quick_reply",  # Corregido: Google Chat exige actionMethodName
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
                            "actionMethodName": "quick_reply",  # Corregido: Google Chat exige actionMethodName
                            "parameters": [
                                {"key": "action", "value": "quick_reply"},
                                {"key": "reply", "value": "No"}
                            ]
                        }
                    }
                }
            ])

        if tipo in {"ALL", "RESET_ONLY"}:
            botones.append({
                "text": "🔄 Cambiar tema",
                "onClick": {
                    "action": {
                        "actionMethodName": "reset",  # Corregido: Google Chat exige actionMethodName
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
        return [{
            "cardId": unique_card_id,
            "card": {
                "sections": [{
                    "widgets": [{
                        "buttonList": {
                            "buttons": botones
                        }
                    }]
                }]
            }
        }]

    async def enviar_mensaje(
        self,
        space_name: str,
        thread_name: Optional[str],
        texto: str,
        tipo_botones: str = "NONE",
        is_dm: bool = False
    ) -> bool:
        token = await obtener_token_google_chat()
        if not token:
            logger.warning("[GOOGLE CHAT REST] No se pudo obtener token OAuth.")
            return False
        if not space_name:
            logger.warning("[GOOGLE CHAT REST] space_name ausente.")
            return False

        url = f"https://chat.googleapis.com/v1/{space_name}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload: dict = {"text": texto}
        params: dict = {}

        if thread_name and not is_dm:
            payload["thread"] = {"name": thread_name}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        cards = self.construir_cards_v2(tipo_botones=tipo_botones)
        if cards:
            payload["cardsV2"] = cards

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload, params=params)
                if resp.status_code == 200:
                    logger.info("[GOOGLE CHAT REST] Mensaje publicado con éxito (DM=%s).", is_dm)
                    return True
                else:
                    logger.error("[GOOGLE CHAT REST ERROR] Status %d: %s", resp.status_code, resp.text)
                    if resp.status_code == 400 and not is_dm:
                        logger.warning("[GOOGLE CHAT REST] Falló envío en hilo, reintentando plano...")
                        payload.pop("thread", None)
                        resp_retry = await client.post(url, headers=headers, json=payload, params={})
                        if resp_retry.status_code == 200:
                            return True
                    return False
        except Exception as error:
            logger.error("[GOOGLE CHAT REST ERROR] Excepción al enviar mensaje: %s", error)
            return False

    async def enviar_mensaje_rescate(self, event: GoogleChatEventDTO, mensaje: str) -> None:
        try:
            space_name, _ = event.get_space()
            thread_name = event.get_thread_name()
            is_dm = event.is_dm()
            await self.enviar_mensaje(
                space_name=space_name,
                thread_name=thread_name,
                texto=mensaje,
                tipo_botones="RESET_ONLY",
                is_dm=is_dm
            )
        except Exception as error:
            logger.error("[GOOGLE CHAT ERROR] No se pudo enviar mensaje de rescate: %s", error)

    async def descargar_imagen_adjunta(self, event: GoogleChatEventDTO) -> Optional[str]:
        attachments = event.get_attachments()
        if not attachments:
            return None

        token = await obtener_token_google_chat()
        if not token:
            return None

        exts_imagen = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
        for adjunto in attachments:
            content_type = adjunto.contentType or ""
            content_name = adjunto.contentName or ""
            resource_name = ""

            if adjunto.attachmentDataRef and adjunto.attachmentDataRef.resourceName:
                resource_name = adjunto.attachmentDataRef.resourceName
            elif adjunto.name:
                resource_name = adjunto.name

            is_image = (
                content_type.startswith("image/")
                or any(content_name.lower().endswith(ext) for ext in exts_imagen)
                or any(resource_name.lower().endswith(ext) for ext in exts_imagen)
            )

            if not is_image and (not content_type or content_type == "application/octet-stream"):
                is_image = True

            if is_image and resource_name:
                if not content_type or not content_type.startswith("image/"):
                    content_type = "image/jpeg"

                download_url = f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media"
                headers = {"Authorization": f"Bearer {token}"}

                try:
                    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                        response = await client.get(download_url, headers=headers)
                        if response.status_code == 200 and response.content:
                            raw_b64 = base64.b64encode(response.content).decode("utf-8")
                            return f"data:{content_type};base64,{raw_b64}"
                except Exception as error:
                    logger.error("[GOOGLE CHAT ERROR] Excepción al descargar imagen: %s", error)
        return None

    async def procesar_evento_chat(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository
    ) -> None:
        space_name, space_type = event.get_space()
        thread_name = event.get_thread_name()
        user_name = event.get_user_display_name()
        user_id = event.get_user_id()
        is_dm = event.is_dm()
        is_button = event.is_button_click()
        action_params = event.get_action_parameters()
        invoked_function = event.get_invoked_function()

        if event.type == "ADDED_TO_SPACE":
            msg_bienvenida = (
                "¡Hola! 👋 Soy tu Asistente Técnico de TI Nivel 1.\n\n"
                "Estoy aquí para ayudarte con problemas relacionados a SAP, VPN GlobalProtect / FortiClient, "
                "WPass, Citrix, impresoras, red y accesos.\n\n¿En qué te puedo ayudar hoy?"
            )
            await self.enviar_mensaje(space_name, None, msg_bienvenida, "NONE", is_dm)
            return

        if event.type == "REMOVED_FROM_SPACE":
            return

        hilo_destino = thread_name if not is_dm else None

        conversation_id = self.calcular_conversation_id(
            space_type="DM" if is_dm else space_type,
            space_name=space_name,
            thread_name=hilo_destino or "",
            user_id=user_id
        )

        is_reset_action = (
            invoked_function in {"reset", "reset_context"}
            or action_params.get("action") in {"reset", "reset_context"}
        )
        seleccion_boton = (action_params.get("reply") or action_params.get("value") or "").strip()
        pregunta = seleccion_boton or event.get_text_content()

        if is_reset_action or (pregunta and pregunta.lower() in COMANDOS_RESET):
            await asyncio.to_thread(conversation_repo.eliminar_conversacion, conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            await self.enviar_mensaje(space_name, hilo_destino, msg_reset, "NONE", is_dm)
            return

        image_base64 = await self.descargar_imagen_adjunta(event)
        tiene_adjunto = bool(event.get_attachments())

        if not pregunta and not image_base64 and not tiene_adjunto:
            msg_bienvenida = (
                f"¡Hola, {user_name}! 👋 Soy tu Asistente Técnico de TI Nivel 1.\n\n"
                "¿En qué te puedo ayudar hoy?"
            )
            await self.enviar_mensaje(space_name, hilo_destino, msg_bienvenida, "NONE", is_dm)
            return

        if not pregunta and (image_base64 or tiene_adjunto):
            if not image_base64 and tiene_adjunto:
                msg_aviso_fallo_img = (
                    "⚠️ Detecté que enviaste un archivo adjunto, pero no fue posible descargarlo. "
                    "Asegúrate de que sea una imagen válida (.png, .jpg) o describe el error que visualizas."
                )
                await self.enviar_mensaje(space_name, hilo_destino, msg_aviso_fallo_img, "RESET_ONLY", is_dm)
                return
            pregunta = "Analiza esta imagen adjunta y diagnostica el problema técnico mostrado."

        respuesta, mostrar_botones = await rag_service.responder(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            pregunta=pregunta,
            image_base64=image_base64
        )

        if mostrar_botones:
            tipo_botones = "ALL"
        else:
            tipo_botones = "NONE"

        await self.enviar_mensaje(space_name, hilo_destino, respuesta, tipo_botones, is_dm)