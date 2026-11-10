import asyncio
import logging
from typing import Any, Awaitable, Callable, List, Optional

from app.prompts.system_prompt import construir_prompt
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.services.interfaces.llm_service import ILLMService
from app.core.config import settings
from app.core.messages import MENSAJE_ERROR_RESCATE

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
    def __init__(
        self,
        conversation_repo: IConversationRepository,
        vector_repo: IVectorRepository,
        llm_service: ILLMService
    ) -> None:
        self.conversation_repo = conversation_repo
        self.vector_repo = vector_repo
        self.llm_service = llm_service

    async def _invocar_llm_con_reintentos(
        self,
        operacion: Callable[[], Awaitable[Any]],
        descripcion: str,
        validador: Optional[Callable[[Any], bool]] = None
    ) -> Any:
        ultimo_error: Optional[Exception] = None
        intentos_totales = settings.MAX_RETRIES_LLM + 1

        for intento in range(1, intentos_totales + 1):
            try:
                resultado = await asyncio.wait_for(
                    operacion(),
                    timeout=settings.REQUEST_TIMEOUT_SECONDS
                )
                if validador is None or validador(resultado):
                    return resultado
                ultimo_error = RuntimeError(f"{descripcion}: el LLM devolvió respuesta vacía")
            except asyncio.TimeoutError:
                ultimo_error = asyncio.TimeoutError(f"{descripcion}: timeout {settings.REQUEST_TIMEOUT_SECONDS}s")
            except Exception as error:
                ultimo_error = error

            if intento < intentos_totales:
                await asyncio.sleep(0.8 * intento)

        if ultimo_error:
            raise ultimo_error
        raise RuntimeError(f"{descripcion}: sin respuesta del LLM")

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        logger.info("[RAG] Búsqueda vectorial para: '%s'", pregunta)
        embedding = await self._invocar_llm_con_reintentos(
            lambda: self.llm_service.generar_embedding(pregunta),
            "generación de embedding",
            validador=bool
        )
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

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> tuple[str, bool]:
        logger.info("[RAG] Consulta — usuario: %s (%s): %s", user_name, conversation_id, pregunta)

        if image_base64 and not (pregunta or "").strip():
            pregunta = "Analiza esta imagen y dime cuál es el problema."

        title = pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        await asyncio.to_thread(
            self.conversation_repo.crear_o_actualizar_conversacion,
            conversation_id, user_id, user_name, title
        )

        descripcion_imagen = ""
        if image_base64:
            try:
                descripcion_imagen = await self._invocar_llm_con_reintentos(
                    lambda: self.llm_service.extraer_descripcion_imagen(image_base64),
                    "análisis de imagen"
                )
            except Exception as error:
                logger.warning("[RAG LLM] Falló análisis de imagen: %s", error)

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
        pregunta_normalizada = "".join(
            c for c in pregunta_limpia if c.isalnum() or c.isspace()
        ).strip()

        # 1. CIERRE (No botones)
        if any(frase in pregunta_limpia for frase in FRASES_EXITO):
            despedida = (
                f"¡Excelente, {user_name}! 🎉 Me alegra mucho que hayas podido resolver el problema. "
                "Si en el futuro tienes otra consulta técnica, aquí estaré para ayudarte."
            )
            await asyncio.to_thread(self.conversation_repo.limpiar_estado, conversation_id)
            await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "user", pregunta)
            await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "assistant", despedida)
            return despedida, False

        # 2. SALUDO (No botones)
        if pregunta_normalizada in SALUDOS and not historial and not image_base64:
            respuesta_saludo = (
                f"¡Hola, {user_name}! 👋\n\n"
                "Soy tu Asistente Técnico de TI Nivel 1. ¿En qué problema te puedo ayudar hoy?"
            )
            await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "user", pregunta)
            await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "assistant", respuesta_saludo)
            return respuesta_saludo, False

        es_respuesta_corta = (pregunta_limpia in RESPUESTAS_SEGUIMIENTO or (len(pregunta.split()) <= 2 and bool(historial)))

        if not root_issue and not es_respuesta_corta and len(pregunta.split()) >= 3:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()
            await asyncio.to_thread(self.conversation_repo.actualizar_estado_conversacion, conversation_id, root_issue, None)

        resolvio_bloqueo = any(frase in pregunta_limpia for frase in FRASES_RECUPERACION)

        if resolvio_bloqueo and root_issue:
            consulta_busqueda = f"{root_issue} pasos solución"
        elif es_respuesta_corta:
            consulta_busqueda = None
        elif descripcion_imagen:
            terminos_limpios = descripcion_imagen.replace("Sistema:", "").replace("Error:", "").replace("1.", "").replace("2.", "").strip()
            consulta_busqueda = " ".join(terminos_limpios.split()[:25])
        else:
            consulta_busqueda = pregunta

        contexto: Optional[str] = None

        if consulta_busqueda:
            contexto = await self.recuperar_contexto(pregunta=consulta_busqueda)

        if contexto:
            await asyncio.to_thread(self.conversation_repo.actualizar_estado_conversacion, conversation_id, None, contexto)
        elif last_context:
            contexto = last_context
        elif es_respuesta_corta and historial:
            mensajes_previos = [m.content for m in historial if m.role == "user"]
            if mensajes_previos:
                contexto = await self.recuperar_contexto(pregunta=mensajes_previos[-1])
                if contexto:
                    await asyncio.to_thread(self.conversation_repo.actualizar_estado_conversacion, conversation_id, None, contexto)
        elif image_base64:
            contexto = (
                f"Diagnóstico visual en pantalla: {descripcion_imagen}. "
                "Examina directamente la imagen adjunta para guiar al usuario."
            )

        pregunta_efectiva = pregunta
        if image_base64 and descripcion_imagen:
            if "analiza esta imagen" in pregunta.lower() or len(pregunta.split()) <= 4:
                pregunta_efectiva = (
                    f"Analiza la captura. En la pantalla se visualiza: {descripcion_imagen}. "
                    "Diagnostica el problema técnico y entrégame el primer paso de solución."
                )
            else:
                pregunta_efectiva = f"{pregunta}\n[Visualizado en pantalla: {descripcion_imagen}]"

        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta_efectiva,
            contexto=contexto or "",
            historial=historial,
            root_issue=root_issue
        )

        try:
            respuesta = await self._invocar_llm_con_reintentos(
                lambda: self.llm_service.generar_respuesta(prompt, image_base64),
                "generación de respuesta",
                validador=lambda texto: bool(texto and texto.strip())
            )
        except Exception as error:
            logger.error("[RAG LLM FATAL] Se agotaron intentos: %s", error)
            return MENSAJE_ERROR_RESCATE, False

        await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "user", mensaje_usuario_bd)
        await asyncio.to_thread(self.conversation_repo.agregar_mensaje, conversation_id, user_id, user_name, "assistant", respuesta)

        # 3. RESPUESTA NORMAL TÉCNICA (Siempre se muestran los 3 botones)
        mostrar_botones = True
        
        logger.info("[RAG] Respuesta lista. mostrar_botones=True forzado.")
        return respuesta, mostrar_botones