import asyncio
import logging
from typing import List, Optional
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from app.core.config import settings
from app.prompts.system_prompt import construir_prompt
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository

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
    Servicio de orquestación de RAG, embeddings y generación multimodal con Gemini.
    Desacoplado de frameworks web y controladores. Inyectado con repositorios abstractos.
    """

    def __init__(
        self,
        conversation_repo: IConversationRepository,
        vector_repo: IVectorRepository,
        embedding_model: Optional[GoogleGenerativeAIEmbeddings] = None,
        llm: Optional[ChatGoogleGenerativeAI] = None
    ):
        self.conversation_repo = conversation_repo
        self.vector_repo = vector_repo
        self.embedding_model = embedding_model or GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY or None
        )
        self.llm = llm or ChatGoogleGenerativeAI(
            model=settings.CHAT_MODEL,
            temperature=0.2,
            google_api_key=settings.GOOGLE_API_KEY or None
        )

    async def generar_embedding(self, texto: str) -> List[float]:
        """Genera vector de embeddings encapsulado en thread pool para evitar bloquear el event loop."""
        return await asyncio.to_thread(self.embedding_model.embed_query, texto)

    async def extraer_descripcion_imagen(self, image_base64: str) -> str:
        """Extrae términos técnicos clave de la captura mediante LLM multimodal."""
        try:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            prompt_extraccion = (
                "Actúa como un analizador técnico de TI. Observa esta imagen y responde en 1 sola línea breve: "
                "el nombre del software o sistema involucrado y el mensaje o código de error textual exacto. "
                "Responde únicamente palabras clave técnicas concisas."
            )
            mensaje = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_extraccion},
                    {"type": "image_url", "image_url": {"url": image_data_uri}}
                ]
            )
            res = await asyncio.to_thread(self.llm.invoke, [mensaje])
            texto = res.content
            if isinstance(texto, list):
                texto = "".join(b if isinstance(b, str) else b.get("text", "") for b in texto)
            descripcion = str(texto).strip()
            logger.info("[RAG] Términos técnicos extraídos de imagen: %s", descripcion)
            return descripcion
        except Exception as e:
            logger.warning("[RAG AVISO] No se pudo analizar la imagen previamente: %s", e)
            return ""

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        """Recupera fragmentos de manuales técnicos en la base vectorial con umbral de similitud."""
        logger.info("[RAG] Búsqueda vectorial para: '%s'", pregunta)
        embedding = await self.generar_embedding(pregunta)
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

        if not contexto:
            return None

        return "\n\n".join(contexto)

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> str:
        """
        Orquesta el ciclo completo de RAG con Gemini y persistencia atómica.
        """
        logger.info("[RAG] Consulta recibida para usuario %s (%s): %s", user_name, conversation_id, pregunta)

        title = pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        await asyncio.to_thread(
            self.conversation_repo.crear_o_actualizar_conversacion,
            conversation_id, user_id, user_name, title
        )

        descripcion_imagen = ""
        if image_base64:
            descripcion_imagen = await self.extraer_descripcion_imagen(image_base64)

        mensaje_usuario_bd = (
            f"[Imagen: {descripcion_imagen}] {pregunta}".strip()
            if (image_base64 and descripcion_imagen)
            else f"[Imagen adjunta] {pregunta}".strip() if image_base64 else pregunta
        )

        historial = await asyncio.to_thread(
            self.conversation_repo.obtener_historial, conversation_id, 8
        )
        estado_conv = await asyncio.to_thread(
            self.conversation_repo.obtener_estado_conversacion, conversation_id
        )
        root_issue = estado_conv.root_issue
        last_context = estado_conv.last_context

        pregunta_limpia = pregunta.strip().lower()
        pregunta_normalizada = "".join(c for c in pregunta_limpia if c.isalnum() or c.isspace()).strip()

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

        es_respuesta_corta = pregunta_limpia in RESPUESTAS_SEGUIMIENTO or (len(pregunta.split()) <= 2 and bool(historial))

        if not root_issue and not es_respuesta_corta and len(pregunta.split()) >= 3:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, root_issue, None
            )
            logger.info("[RAG] Objetivo raíz establecido: %s", root_issue)

        resolvio_bloqueo = any(frase in pregunta_limpia for frase in FRASES_RECUPERACION)

        if resolvio_bloqueo and root_issue:
            logger.info("[RAG] Detectada resolución de bloqueo. Retomando objetivo raíz...")
            consulta_busqueda = f"{root_issue} pasos solución"
        elif es_respuesta_corta:
            consulta_busqueda = None
        elif descripcion_imagen:
            consulta_busqueda = f"{pregunta} {descripcion_imagen}".strip()
        else:
            consulta_busqueda = pregunta

        contexto = None
        if consulta_busqueda:
            contexto = await self.recuperar_contexto(pregunta=consulta_busqueda)

        if contexto:
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, None, contexto
            )
        elif last_context:
            logger.info("[RAG] Reutilizando manual activo guardado en BD.")
            contexto = last_context
        elif es_respuesta_corta and historial:
            logger.info("[RAG SEGURIDAD] Reconstruyendo contexto desde historial...")
            mensajes_usuario_previos = [m["content"] for m in historial if m["role"] == "user"]
            if mensajes_usuario_previos:
                consulta_recuperada = mensajes_usuario_previos[-1]
                contexto = await self.recuperar_contexto(pregunta=consulta_recuperada)
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

        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial,
            root_issue=root_issue
        )

        if image_base64:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            mensaje_llm = HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_uri}}
            ])
        else:
            mensaje_llm = HumanMessage(content=prompt)

        respuesta_llm = await asyncio.to_thread(self.llm.invoke, [mensaje_llm])
        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = [b if isinstance(b, str) else b.get("text", "") for b in contenido]
            respuesta = "".join(partes)
        else:
            respuesta = str(contenido)

        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "user", mensaje_usuario_bd
        )
        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "assistant", respuesta
        )

        logger.info("[RAG] Respuesta generada y guardada exitosamente.")
        return respuesta