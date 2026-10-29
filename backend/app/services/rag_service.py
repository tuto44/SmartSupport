import asyncio
import logging
from typing import List, Optional

from app.prompts.system_prompt import construir_prompt
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.services.interfaces.llm_service import ILLMService
from app.core.config import settings

logger = logging.getLogger(__name__)

SALUDOS = {
    "hola", "buenas", "buen dia", "buen día", "buenos dias", "buenos días",
    "buenas tardes", "buenas noches", "hey", "saludos", "hola!", "que tal", "qué tal", "iniciar"
}

RESPUESTAS_SEGUIMIENTO = {
    "si", "sí", "no", "ya", "ya lo hice", "listo", "no funcionó",
    "no me deja", "ok", "vale", "ya está", "ya termine", "ya terminé",
    "funciono", "funcionó", "siguiente", "continuar", "sigue igual"
}

FRASES_RECUPERACION = {
    "ya tengo internet", "ya cargo", "ya cargó", "ya navega",
    "ya volvio el internet", "ya volvió el internet", "ya conecto el wifi",
    "ya tengo red", "ya dio ip", "ya conecto internet"
}


class RagService:
    """
    Servicio de orquestación del ciclo RAG (Retrieval-Augmented Generation).

    Principios aplicados:
    - SRP: exclusivamente orquesta RAG; no gestiona HTTP ni persistencia directa.
    - DIP: recibe contratos abstractos (IConversationRepository, IVectorRepository,
           ILLMService) inyectados en el constructor.
    - Todas las operaciones I/O bloqueantes se delegan a asyncio.to_thread.
    """

    def __init__(
        self,
        conversation_repo: IConversationRepository,
        vector_repo: IVectorRepository,
        llm_service: ILLMService
    ) -> None:
        self.conversation_repo = conversation_repo
        self.vector_repo = vector_repo
        self.llm_service = llm_service

    # ------------------------------------------------------------------ #
    #  Recuperación de Contexto Vectorial                                  #
    # ------------------------------------------------------------------ #

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        """Recupera fragmentos de manuales técnicos con umbral de similitud."""
        logger.info("[RAG] Búsqueda vectorial para: '%s'", pregunta)
        embedding = await self.llm_service.generar_embedding(pregunta)
        resultados = await asyncio.to_thread(
            self.vector_repo.buscar_similares, embedding, limite
        )

        if not resultados:
            return None

        contexto = []
        for resultado in resultados:
            score = getattr(resultado, "score", 0.0)
            if score < settings.MIN_SIMILARITY_SCORE:
                continue
            payload = getattr(resultado, "payload", {}) or {}
            contenido = payload.get("page_content")
            if contenido:
                contexto.append(contenido)

        return "\n\n".join(contexto) if contexto else None

    # ------------------------------------------------------------------ #
    #  Ciclo principal de respuesta                                        #
    # ------------------------------------------------------------------ #

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> str:
        """Orquesta el ciclo completo de RAG con Gemini y persistencia atómica."""
        logger.info(
            "[RAG] Consulta recibida — usuario: %s (%s): %s",
            user_name, conversation_id, pregunta
        )

        title = pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        await asyncio.to_thread(
            self.conversation_repo.crear_o_actualizar_conversacion,
            conversation_id, user_id, user_name, title
        )

        # — Análisis de imagen adjunta —
        descripcion_imagen = ""
        if image_base64:
            descripcion_imagen = await self.llm_service.extraer_descripcion_imagen(image_base64)

        mensaje_usuario_bd = (
            f"[Imagen: {descripcion_imagen}] {pregunta}".strip()
            if (image_base64 and descripcion_imagen)
            else f"[Imagen adjunta] {pregunta}".strip() if image_base64 else pregunta
        )

        # — Recuperar historial y estado —
        historial = await asyncio.to_thread(
            self.conversation_repo.obtener_historial, conversation_id, 8
        )
        estado_conv = await asyncio.to_thread(
            self.conversation_repo.obtener_estado_conversacion, conversation_id
        )
        root_issue = estado_conv.root_issue
        last_context = estado_conv.last_context

        pregunta_limpia = pregunta.strip().lower()
        pregunta_normalizada = "".join(
            c for c in pregunta_limpia if c.isalnum() or c.isspace()
        ).strip()

        # — Saludo inicial —
        if pregunta_normalizada in SALUDOS and not historial:
            respuesta_saludo = (
                f"¡Hola, {user_name}! 👋\n\n"
                "Soy tu Asistente Técnico de TI Nivel 1. ¿En qué problema, sistema o requerimiento "
                "(VPN, WPass, Citrix, correo, accesos, impresoras) te puedo ayudar hoy?"
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", pregunta
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_saludo
            )
            return respuesta_saludo

        es_respuesta_corta = (
            pregunta_limpia in RESPUESTAS_SEGUIMIENTO
            or (len(pregunta.split()) <= 2 and bool(historial))
        )

        # — Establecer objetivo raíz —
        if not root_issue and not es_respuesta_corta and len(pregunta.split()) >= 3:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, root_issue, None
            )
            logger.info("[RAG] Objetivo raíz establecido: %s", root_issue)

        # — Estrategia de búsqueda —
        resolvio_bloqueo = any(frase in pregunta_limpia for frase in FRASES_RECUPERACION)

        if resolvio_bloqueo and root_issue:
            logger.info("[RAG] Resolución de bloqueo detectada. Retomando objetivo raíz...")
            consulta_busqueda: Optional[str] = f"{root_issue} pasos solución"
        elif es_respuesta_corta:
            consulta_busqueda = None
        elif descripcion_imagen:
            consulta_busqueda = f"{pregunta} {descripcion_imagen}".strip()
        else:
            consulta_busqueda = pregunta

        contexto: Optional[str] = None
        if consulta_busqueda:
            contexto = await self.recuperar_contexto(pregunta=consulta_busqueda)

        if contexto:
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, None, contexto
            )
        elif last_context:
            logger.info("[RAG] Reutilizando manual activo guardado en base de datos.")
            contexto = last_context
        elif es_respuesta_corta and historial:
            logger.info("[RAG] Reconstruyendo contexto desde historial previo...")
            mensajes_previos = [m["content"] for m in historial if m["role"] == "user"]
            if mensajes_previos:
                contexto = await self.recuperar_contexto(pregunta=mensajes_previos[-1])
                if contexto:
                    await asyncio.to_thread(
                        self.conversation_repo.actualizar_estado_conversacion,
                        conversation_id, None, contexto
                    )
        elif image_base64:
            contexto = (
                "No se encontró un manual específico en la base de conocimientos. "
                "Diagnostica el problema técnico analizando visualmente la imagen adjunta."
            )

        # — Sin contexto disponible —
        if not contexto:
            respuesta_sin_doc = (
                "No encontré información relacionada con tu consulta en la documentación disponible. "
                "Te recomiendo contactar al área de TI."
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", mensaje_usuario_bd
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_sin_doc
            )
            return respuesta_sin_doc

        # — Construir prompt y generar respuesta —
        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial,
            root_issue=root_issue
        )

        respuesta = await self.llm_service.generar_respuesta(prompt, image_base64)

        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "user", mensaje_usuario_bd
        )
        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "assistant", respuesta
        )

        logger.info("[RAG] Respuesta generada y persistida exitosamente.")
        return respuesta
