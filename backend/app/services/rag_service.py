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

FRASES_EXITO = {
    "ya funcionó", "ya funciono", "ya sirvió", "ya sirvio",
    "ya pude", "ya pude entrar", "ya quedó", "ya quedo",
    "listo ya quedó", "listo ya quedo", "perfecto gracias",
    "solucionado", "gracias funciono", "gracias funcionó",
    "ya entré", "ya entre", "ya abre", "ya carga", "ya cargó",
    "problema resuelto", "ya lo resolví", "ya lo resolvi",
    "muchas gracias", "excelente gracias", "todo bien gracias",
    "ya está resuelto", "ya esta resuelto", "listo gracias",
    "ya se solucionó", "ya se soluciono", "ya quedó listo"
}


class RagService:
    """
    Servicio de orquestación del ciclo RAG (Retrieval-Augmented Generation).

    Principios aplicados:
    - SRP: exclusivamente orquesta RAG; no gestiona HTTP ni persistencia directa.
    - DIP: recibe contratos abstractos (IConversationRepository, IVectorRepository, ILLMService) inyectados en el constructor.
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
    #  Recuperación de Contexto Vectorial                                #
    # ------------------------------------------------------------------ #

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        """Recupera fragmentos de manuales técnicos filtrando estrictamente por umbral de similitud."""
        logger.info("[RAG] Búsqueda vectorial para: '%s'", pregunta)
        embedding = await self.llm_service.generar_embedding(pregunta)
        resultados = await asyncio.to_thread(
            self.vector_repo.buscar_similares, embedding, limite
        )

        if not resultados:
            return None

        # Validación de confianza: comprobar el score del mejor resultado (Top 1)
        top_score = getattr(resultados[0], "score", 0.0)
        if top_score < settings.MIN_SIMILARITY_SCORE:
            logger.info(
                "[RAG] Consulta sin coincidencia relevante en base de conocimiento. Top Score=%.3f (Umbral=%.2f)",
                top_score, settings.MIN_SIMILARITY_SCORE
            )
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
    #  Ciclo principal de respuesta                                       #
    # ------------------------------------------------------------------ #

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> tuple[str, bool]:
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

        # — Detección de cierre exitoso de incidente —
        if any(frase in pregunta_limpia for frase in FRASES_EXITO):
            logger.info("[RAG] Cierre de incidente detectado para: %s", user_name)
            despedida = (
                f"¡Excelente, {user_name}! 🎉 Me alegra mucho que hayas podido resolver el problema. "
                "Si en el futuro tienes otra consulta técnica, aquí estaré para ayudarte. "
                "¡Que tengas un excelente día!"
            )
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, None, None
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", pregunta
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", despedida
            )
            return despedida, False

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
            return respuesta_saludo, False

        es_respuesta_corta = (
            pregunta_limpia in RESPUESTAS_SEGUIMIENTO
            or (len(pregunta.split()) <= 2 and bool(historial))
        )

        # — Establecer o evaluar objetivo raíz —
        if not root_issue and not es_respuesta_corta and len(pregunta.split()) >= 3:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()

        # — Reformulación Contextual de Consultas (Contextual Query Rewriting) —
        resolvio_bloqueo = any(frase in pregunta_limpia for frase in FRASES_RECUPERACION)

        if resolvio_bloqueo and root_issue:
            logger.info("[RAG] Resolución de bloqueo detectada. Reformulando consulta con el objetivo raíz...")
            consulta_busqueda: Optional[str] = f"{root_issue} pasos solución"
        elif es_respuesta_corta and root_issue:
            logger.info("[RAG] Reformulación Contextual: Enriqueciendo respuesta corta con Root Issue...")
            consulta_busqueda = f"{root_issue} {pregunta}".strip()
        elif descripcion_imagen:
            consulta_busqueda = f"{pregunta} {descripcion_imagen}".strip()
        else:
            consulta_busqueda = pregunta

        contexto: Optional[str] = None
        if consulta_busqueda:
            contexto = await self.recuperar_contexto(pregunta=consulta_busqueda)

        # Si se encontró contexto válido, actualizar el estado de la conversación
        if contexto:
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, root_issue, contexto
            )
        elif last_context and es_respuesta_corta:
            logger.info("[RAG] Reutilizando manual activo guardado en base de datos para seguimiento corto.")
            contexto = last_context

        # — Sin contexto disponible: derivación formal —
        if not contexto:
            respuesta_sin_doc = (
                f"⚠️ Hola, {user_name}. No encontré un procedimiento o manual oficial en la base de conocimientos "
                f"relacionado con **{pregunta}**.\n\n"
                "Para obtener asistencia con esta solicitud, te sugiero:\n"
                "1. 📋 Generar un ticket en el portal **My Whirlpool** (*IT Service Catalog* > **Something's Broken** / **Submit an Incident**).\n"
                "2. 📞 Escalar el caso directamente con la Mesa de Ayuda de TI Nivel 2 o el **Departamento de TI de HWI**."
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", mensaje_usuario_bd
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_sin_doc
            )
            return respuesta_sin_doc, False

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
        return respuesta, True