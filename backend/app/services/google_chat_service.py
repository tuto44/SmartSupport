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
    - Construcción dinámica de cards y botones interactivos V2 (Sí/No configurables y Cambiar tema persistente).
    - Publicación garantizada mediante la API REST oficial de Google Chat con soporte de hilos y fallback.
    - Soporte multimodal con seguimiento de redirecciones HTTP 302/307 hacia Google Cloud Storage.
    - Respuestas síncronas adecuadas (actionResponse NEW_MESSAGE con texto) para asegurar la ejecución inmediata de botones.
    """

    @staticmethod
    def _hash_usuario(user_id: str) -> str:
        base = (user_id or "anonimo").encode("utf-8")
        return hashlib.sha256(base).hexdigest()[:12]

    @staticmethod
    def calcular_conversation_id(space_type: str, space_name: str, thread_name: str, user_id: str) -> str:
        sufijo_usuario = GoogleChatService._hash_usuario(user_id)

        if space_type == "DM" and space_name:
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
                            "function": "quick_reply",
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
                            "function": "quick_reply",
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
                        "function": "reset",
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
        tipo_botones: str = "NONE"
    ) -> bool:
        """
        Publica el mensaje directamente en el espacio de Google Chat usando la API REST oficial.
        Incluye messageReplyOption para asegurar que tanto Spaces con hilos como DMs acepten el mensaje.
        """
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

        # CRÍTICO: messageReplyOption SOLO es válido cuando se especifica thread.
        # Si thread_name es None y se envía messageReplyOption, Google Chat rechaza la petición
        # con HTTP 400: "The request does not specify which message to reply to."
        if thread_name:
            payload["thread"] = {"name": thread_name}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        cards = self.construir_cards_v2(tipo_botones=tipo_botones)
        if cards:
            payload["cardsV2"] = cards

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload, params=params)
                if resp.status_code == 200:
                    logger.info(
                        "[GOOGLE CHAT REST] Mensaje publicado con éxito en %s (hilo=%s).",
                        space_name, bool(thread_name)
                    )
                    return True
                else:
                    logger.error(
                        "[GOOGLE CHAT REST ERROR] Status %d: %s (payload thread=%s)",
                        resp.status_code, resp.text, thread_name
                    )
                    # Si falló por restricción de thread o reply option, reintentar limpio
                    if resp.status_code == 400:
                        logger.warning("[GOOGLE CHAT REST] Reintentando envío limpio sin thread ni reply options...")
                        payload.pop("thread", None)
                        resp_retry = await client.post(url, headers=headers, json=payload, params={})
                        if resp_retry.status_code == 200:
                            logger.info("[GOOGLE CHAT REST] Reintento limpio publicado con éxito.")
                            return True
                    return False
        except Exception as error:
            logger.error("[GOOGLE CHAT REST ERROR] Excepción al enviar mensaje: %s", error)
            return False

    async def enviar_mensaje_rescate(self, event: GoogleChatEventDTO, mensaje: str) -> None:
        """Envía un mensaje de rescate amigable si ocurre un fallo o timeout."""
        try:
            space_name, _ = event.get_space()
            thread_name = event.get_thread_name()
            await self.enviar_mensaje(
                space_name=space_name,
                thread_name=thread_name,
                texto=mensaje,
                tipo_botones="RESET_ONLY"
            )
        except Exception as error:
            logger.error("[GOOGLE CHAT ERROR] No se pudo enviar mensaje de rescate: %s", error)

    async def descargar_imagen_adjunta(self, event: GoogleChatEventDTO) -> Optional[str]:
        """
        Descarga autenticada de imagen adjunta con soporte de redirecciones 302/307
        hacia Google Cloud Storage.
        """
        attachments = event.get_attachments()
        if not attachments:
            return None

        token = await obtener_token_google_chat()
        if not token:
            logger.warning("[GOOGLE CHAT] No se pudo obtener token OAuth para descargar adjunto.")
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
                    logger.info(
                        "[GOOGLE CHAT] Descargando imagen adjunta: %s (archivo: %s, tipo: %s)",
                        resource_name, content_name or "sin_nombre", content_type
                    )
                    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                        response = await client.get(download_url, headers=headers)
                        if response.status_code == 200 and response.content:
                            raw_b64 = base64.b64encode(response.content).decode("utf-8")
                            logger.info(
                                "[GOOGLE CHAT] Imagen descargada y codificada con éxito (%d bytes).",
                                len(response.content)
                            )
                            return f"data:{content_type};base64,{raw_b64}"
                        else:
                            logger.error(
                                "[GOOGLE CHAT ERROR] Fallo al descargar imagen: HTTP %d: %s",
                                response.status_code, response.text[:200]
                            )
                except Exception as error:
                    logger.error("[GOOGLE CHAT ERROR] Excepción al descargar imagen: %s", error)

        return None

    async def procesar_evento_chat(
        self,
        event: GoogleChatEventDTO,
        rag_service: Any,
        conversation_repo: IConversationRepository
    ) -> Dict[str, Any]:
        """
        Orquesta el ciclo completo de recepción, procesamiento y publicación de respuesta.
        Publica el mensaje directamente en el Space y retorna el actionResponse adecuado.
        """
        # --- 1. EVENTOS DE ESPACIO ---
        if event.type == "ADDED_TO_SPACE":
            msg_bienvenida = (
                "¡Hola! 👋 Soy tu Asistente Técnico de TI Nivel 1.\n\n"
                "Estoy aquí para ayudarte con problemas relacionados a SAP, VPN GlobalProtect / FortiClient, "
                "WPass, Citrix, impresoras, red y accesos.\n\n"
                "¿En qué te puedo ayudar hoy?"
            )
            space_name, _ = event.get_space()
            await self.enviar_mensaje(
                space_name=space_name,
                thread_name=None,
                texto=msg_bienvenida,
                tipo_botones="NONE"
            )
            return {}

        if event.type == "REMOVED_FROM_SPACE":
            logger.info("[GOOGLE CHAT] Bot eliminado del espacio.")
            return {}

        # --- 2. EXTRACCIÓN Y ENRUTAMIENTO DETERMINISTA ---
        space_name, space_type = event.get_space()
        thread_name = event.get_thread_name()
        user_name = event.get_user_display_name()
        user_id = event.get_user_id()
        is_dm = event.is_dm()
        is_button = event.is_button_click()
        action_params = event.get_action_parameters()
        invoked_function = event.get_invoked_function()
        is_in_thread = event.is_in_thread()

        # Enrutamiento de hilo seguro:
        # En Spaces organizados por temas, SIEMPRE se debe usar thread_name si existe.
        # En DMs privados 1:1, sólo se usa thread_name si el usuario está dentro de un hilo explícito.
        # En clics de botón, se conserva thread_name para que la respuesta continúe en el mismo contexto.
        if is_button:
            hilo_destino = thread_name or None
        elif is_dm:
            hilo_destino = thread_name if is_in_thread else None
        else:
            hilo_destino = thread_name or None

        logger.info(
            "[ENRUTAMIENTO] user='%s', is_button=%s, is_in_thread=%s, is_dm=%s -> destino_hilo=%s",
            user_name, is_button, is_in_thread, is_dm, hilo_destino or "CHAT_PRINCIPAL"
        )

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
        seleccion_boton = (
            action_params.get("reply")
            or action_params.get("value")
            or ""
        ).strip()
        pregunta = seleccion_boton or event.get_text_content()

        # --- 3. REINICIO DE CONVERSACIÓN (CAMBIAR TEMA) ---
        if is_reset_action or (pregunta and pregunta.lower() in COMANDOS_RESET):
            logger.info("[RAG RESET] Reiniciando conversación para conversation_id='%s'", conversation_id)
            await asyncio.to_thread(conversation_repo.eliminar_conversacion, conversation_id)
            msg_reset = "🔄 *Contexto reiniciado con éxito.*\n\n¿En qué nuevo tema, problema o requerimiento te puedo ayudar?"
            resultado_reset: Dict[str, Any] = {"text": msg_reset}
            if is_button:
                resultado_reset["actionResponse"] = {"type": "NEW_MESSAGE"}
            return resultado_reset

        # --- 4. GESTIÓN MULTIMODAL Y ADJUNTOS ---
        image_base64 = await self.descargar_imagen_adjunta(event)
        tiene_adjunto = bool(event.get_attachments())

        # Caso A: Sin mensaje y sin adjunto (apertura inicial)
        if not pregunta and not image_base64 and not tiene_adjunto:
            msg_bienvenida = (
                f"¡Hola, {user_name}! 👋 Soy tu Asistente Técnico de TI Nivel 1.\n\n"
                "Estoy aquí para ayudarte con problemas relacionados a SAP, VPN (GlobalProtect / FortiClient), "
                "accesos, WPass, Citrix, impresoras y cuentas.\n\n"
                "¿En qué te puedo ayudar hoy?"
            )
            resultado_bienvenida: Dict[str, Any] = {"text": msg_bienvenida}
            if is_button:
                resultado_bienvenida["actionResponse"] = {"type": "NEW_MESSAGE"}
            return resultado_bienvenida

        # Caso B: Imagen enviada sin texto
        if not pregunta and (image_base64 or tiene_adjunto):
            if not image_base64 and tiene_adjunto:
                msg_aviso_fallo_img = (
                    "⚠️ Detecté que enviaste un archivo adjunto, pero no fue posible descargarlo desde los servidores "
                    "de Google Chat. Por favor asegúrate de que sea una imagen válida (.png, .jpg) o describe el error que visualizas."
                )
                cards_fallo = self.construir_cards_v2(tipo_botones="RESET_ONLY")
                resultado_fallo: Dict[str, Any] = {"text": msg_aviso_fallo_img}
                if cards_fallo:
                    resultado_fallo["cardsV2"] = cards_fallo
                if is_button:
                    resultado_fallo["actionResponse"] = {"type": "NEW_MESSAGE"}
                return resultado_fallo

            pregunta = "Analiza esta imagen adjunta y diagnostica el problema técnico o mensaje de error mostrado."

        # --- 5. ORQUESTACIÓN RAG CON PERSISTENCIA ---
        respuesta, mostrar_botones = await rag_service.responder(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            pregunta=pregunta,
            image_base64=image_base64
        )

        # --- 6. DETERMINACIÓN DE BOTONES ---
        if any(f in respuesta.lower() for f in ["excelente", "me alegra", "que tengas un excelente día"]):
            tipo_botones = "NONE"
        elif mostrar_botones:
            tipo_botones = "ALL"
        else:
            tipo_botones = "RESET_ONLY"

        # --- 7. CONSTRUCCIÓN DE RESPUESTA SÍNCRONA PARA GOOGLE CHAT ---
        cards = self.construir_cards_v2(tipo_botones=tipo_botones)
        resultado: Dict[str, Any] = {"text": respuesta}
        if cards:
            resultado["cardsV2"] = cards

        if is_button:
            resultado["actionResponse"] = {"type": "NEW_MESSAGE"}

        logger.info(
            "[GOOGLE CHAT] Enviando respuesta síncrona a %s (botones=%s, is_button=%s)",
            space_name, tipo_botones, is_button
        )
        return resultado
