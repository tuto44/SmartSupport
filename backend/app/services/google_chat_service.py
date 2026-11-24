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
from app.utils.format_utils import formatear_para_google_chat
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
    - Construcción de cards y botones interactivos V2 dinámicos.
    - Envío asíncrono de mensajes y respuestas en hilos/espacios (REST API).
    - Indicador visual único de procesamiento ('⏳ Analizando tu consulta...') actualizado in-place vía PATCH.
    - Respuesta síncrona en el body HTTP 200 como fallback de alta resiliencia.
    - Gestión precisa de hilos (threads) en DMs vs Spaces.
    - Descarga autenticada de imágenes adjuntas vía REST API v1.
    - Procesamiento desacoplado con reintentos y tolerancia a latencia/fallos.
    """

    @staticmethod
    def _mensaje_bienvenida(user_name: str) -> str:
        return (
            f"¡Hola, {user_name}! 👋 Soy **GABI** (*Guía y Asistencia Business Intelligent*), "
            "tu asistente virtual corporativo de soporte TI en HWI.\n\n"
            "Estoy aquí para guiarte paso a paso con los procedimientos técnicos oficiales de la compañía. "
            "Escríbeme tu consulta directamente o pregúntame *¿en qué me puedes ayudar?* para mostrarte los manuales disponibles."
        )

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
    def construir_cards_v2(modo_botones: str | bool = "cerrada") -> list:
        """
        Construye botones dinámicos según el tipo de pregunta del asistente:
        - 'cerrada' (o True): [✅ Sí, ❌ No, 🔄 Cambiar tema]
        - 'abierta': [🔄 Cambiar tema]
        - 'ninguno' (o False): []
        """
        if isinstance(modo_botones, bool):
            modo = "cerrada" if modo_botones else "ninguno"
        else:
            modo = (modo_botones or "ninguno").strip().lower()

        if modo == "ninguno":
            return []

        botones = []
        if modo == "cerrada":
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

    async def publicar_mensaje_temporal(
        self,
        space_name: str,
        thread_name: Optional[str],
        texto: str = "⏳ _Analizando tu consulta..._"
    ) -> Optional[str]:
        """
        Publica un mensaje temporal en Google Chat como indicador de procesamiento
        y retorna su resource name ('spaces/.../messages/...') para actualizarlo luego.
        """
        token = await obtener_token_google_chat()
        if not token or not space_name:
            return None

        url = f"https://chat.googleapis.com/v1/{space_name}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload: dict = {"text": formatear_para_google_chat(texto)}
        if thread_name:
            payload["thread"] = {"name": thread_name}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    msg_name = data.get("name")
                    logger.info("[GOOGLE CHAT] Indicador temporal publicado: %s", msg_name)
                    return msg_name
        except Exception as error:
            logger.debug("[GOOGLE CHAT] No se pudo publicar indicador temporal: %s", error)
        return None

    async def actualizar_mensaje(
        self,
        message_name: str,
        texto: str,
        mostrar_botones: bool | str = "cerrada"
    ) -> bool:
        """
        Reemplaza in-place el mensaje temporal ('⏳ Analizando tu consulta...')
        con la respuesta final formateada y sus botones dinámicos mediante PATCH.
        """
        token = await obtener_token_google_chat()
        if not token or not message_name:
            return False

        texto_formateado = formatear_para_google_chat(texto)
        cards = self.construir_cards_v2(mostrar_botones)

        url = f"https://chat.googleapis.com/v1/{message_name}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload: dict = {"text": texto_formateado}
        update_mask = "text"

        if cards:
            payload["cardsV2"] = cards
            update_mask = "text,cardsV2"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.patch(
                    url,
                    headers=headers,
                    json=payload,
                    params={"updateMask": update_mask}
                )
                if resp.status_code == 200:
                    logger.info("[GOOGLE CHAT] Mensaje actualizado in-place exitosamente (%s).", message_name)
                    return True
                else:
                    logger.warning(
                        "[GOOGLE CHAT ADVERTENCIA] PATCH falló (%d): %s. Se usará envío estándar.",
                        resp.status_code, resp.text[:200]
                    )
                    return False
        except Exception as error:
            logger.warning("[GOOGLE CHAT ADVERTENCIA] Excepción en PATCH (%s): %s", message_name, error)
            return False

    async def enviar_mensaje(
        self,
        space_name: str,
        thread_name: Optional[str],
        texto: str,
        mostrar_botones: bool | str = True
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
        texto_formateado = formatear_para_google_chat(texto)
        cards = self.construir_cards_v2(mostrar_botones)

        url = f"https://chat.googleapis.com/v1/{space_name}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload: dict = {"text": texto_formateado}
        params: dict = {}

        if thread_name:
            payload["thread"] = {"name": thread_name}

        if cards:
            payload["cardsV2"] = cards

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

            resource_path = None
            if adjunto.attachmentDataRef and adjunto.attachmentDataRef.resourceName:
                resource_path = adjunto.attachmentDataRef.resourceName
            elif adjunto.name:
                resource_path = adjunto.name

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

            clean_res = resource_path.lstrip("/")
            if clean_res.startswith("media/"):
                clean_res = clean_res[6:]

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
        conversation_repo: IConversationRepository,
        msg_temp_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Orquesta el ciclo de recepción y respuesta para el evento de Google Chat.
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

        if event.is_added_to_space():
            msg_bienvenida = self._mensaje_bienvenida(user_name)
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=msg_bienvenida,
                mostrar_botones=False
            )
            if not enviado:
                payload_sync = {"text": msg_bienvenida}
                if target_thread:
                    payload_sync["thread"] = {"name": target_thread}
                return payload_sync
            return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

        is_reset_action = (
            invoked_function in {"reset", "reset_context"}
            or action_params.get("action") in {"reset", "reset_context"}
        )
        pregunta = action_params.get("reply") or action_params.get("value") or event.get_text_content()

        if is_reset_action or pregunta.lower() in COMANDOS_RESET:
            await asyncio.to_thread(conversation_repo.eliminar_conversacion, conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            enviado = False
            if msg_temp_name:
                enviado = await self.actualizar_mensaje(
                    message_name=msg_temp_name,
                    texto=msg_reset,
                    mostrar_botones=False
                )
            if not enviado:
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
            pregunta = "Hola"

        if not pregunta and image_base64:
            pregunta = "Revisa la imagen adjunta y diagnostica el problema o error mostrado."

        # Publicar burbuja temporal solo si no fue creada previamente por el gestor de reintentos
        if msg_temp_name is None:
            msg_temp_name = await self.publicar_mensaje_temporal(
                space_name=space_name,
                thread_name=target_thread
            )

        respuesta, modo_botones = await rag_service.responder(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            pregunta=pregunta,
            image_base64=image_base64
        )

        enviado = False
        if msg_temp_name:
            enviado = await self.actualizar_mensaje(
                message_name=msg_temp_name,
                texto=respuesta,
                mostrar_botones=modo_botones
            )

        if not enviado:
            enviado = await self.enviar_mensaje(
                space_name=space_name,
                thread_name=target_thread,
                texto=respuesta,
                mostrar_botones=modo_botones
            )

        if not enviado:
            logger.info("[GOOGLE CHAT] Enviando respuesta de forma síncrona en el body HTTP 200.")
            payload_sync: dict = {"text": respuesta}
            if target_thread:
                payload_sync["thread"] = {"name": target_thread}
            cards = self.construir_cards_v2(modo_botones)
            if cards:
                payload_sync["cardsV2"] = cards
            return payload_sync

        return {"actionResponse": {"type": "TYPE_UNSPECIFIED"}} if is_button else {}

    async def procesar_evento_con_reintentos(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository,
        max_reintentos: int = 2
    ) -> None:
        """
        Ejecuta el procesamiento del evento en segundo plano con una única burbuja
        temporal reutilizable entre reintentos y garantía de respuesta al usuario.
        """
        space_name, _ = event.get_space()
        thread_name = event.get_thread_name()
        is_in_thread = event.is_in_thread()
        target_thread = thread_name if is_in_thread else None

        is_button = event.is_button_click()
        action_params = event.get_action_parameters()
        invoked_function = event.get_invoked_function()
        pregunta_raw = action_params.get("reply") or action_params.get("value") or event.get_text_content()
        es_reset = (
            invoked_function in {"reset", "reset_context"}
            or action_params.get("action") in {"reset", "reset_context"}
            or pregunta_raw.lower() in COMANDOS_RESET
        )

        # Publicar UNA sola burbuja temporal antes de entrar al bucle de reintentos
        msg_temp_name: Optional[str] = None
        if not event.is_added_to_space() and not es_reset and space_name:
            msg_temp_name = await self.publicar_mensaje_temporal(
                space_name=space_name,
                thread_name=target_thread
            )

        intentos = 0
        exito = False

        while intentos < max_reintentos and not exito:
            intentos += 1
            try:
                logger.info("[RESILIENCIA] Procesando evento (intento %d/%d)...", intentos, max_reintentos)
                await self.procesar_evento_chat(
                    event=event,
                    rag_service=rag_service,
                    conversation_repo=conversation_repo,
                    msg_temp_name=msg_temp_name
                )
                exito = True
            except Exception as error:
                logger.error(
                    "[RESILIENCIA ERROR] Fallo en intento %d/%d al procesar evento: %s",
                    intentos, max_reintentos, error, exc_info=True
                )
                if intentos < max_reintentos:
                    await asyncio.sleep(1.0 * intentos)

        if not exito and space_name:
            msg_error = (
                "⚠️ *Inconveniente temporal de conexión*\n\n"
                "El servicio de inteligencia artificial está experimentando alta demanda en este momento. "
                "Por favor, intenta enviar tu consulta de nuevo en unos segundos."
            )
            logger.warning("[RESILIENCIA] Actualizando/enviando respuesta de emergencia a %s", space_name)
            actualizado = False
            if msg_temp_name:
                actualizado = await self.actualizar_mensaje(
                    message_name=msg_temp_name,
                    texto=msg_error,
                    mostrar_botones=False
                )
            if not actualizado:
                await self.enviar_mensaje(
                    space_name=space_name,
                    thread_name=target_thread,
                    texto=msg_error,
                    mostrar_botones=False
                )