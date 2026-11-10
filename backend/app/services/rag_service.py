import asyncio
import logging
import re
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

# Expresiones que indican que el usuario confirmó el cierre exitoso del incidente.
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

# Preguntas que expresan una confirmación binaria sobre un paso del manual.
# Sólo estas habilitan los botones Sí / No / Cambiar tema.
PATRONES_CONFIRMACION = (
    r"\blograste\b",
    r"\bpudiste\b",
    r"\bte\s+funcion[oó]\b",
    r"\bte\s+sirvi[oó]\b",
    r"\bte\s+aparece\b",
    r"\bse\s+muestra\b",
    r"\bse\s+solucion[oó]\b",
    r"\b(?:lo|la)\s+visualizas\b",
    r"\bya\s+(?:carg[oó]|conect[oó]|ingresaste|accediste)\b",
    r"\bcontin[uú]a\s+el\s+(?:error|problema|falla)\b",
    r"\bpersiste\b",
    r"\brecibiste\b",
    r"\bcompletaste\b",
    r"\baccediste\b",
    r"\bingresaste\b",
    r"\bpuedes\s+(?:ingresar|acceder|ver|visualizar)\b",
    r"\bconfirmas\b",
    r"\bdeseas\s+que\s+te\s+gu[ií]e\b",
    r"\bquieres\s+(?:intentar|continuar)\b",
)

# Interrogativos abiertos: nunca deben habilitar botones de confirmación.
PATRONES_PREGUNTA_ABIERTA = (
    r"\bqu[eé]\b",
    r"\bc[oó]mo\b",
    r"\bcu[aá]l(?:es)?\b",
    r"\bd[oó]nde\b",
    r"\bpor\s+qu[eé]\b",
    r"\bcu[aá]ndo\b",
    r"\bqui[eé]n\b",
    r"\bdescribe\b",
    r"\bindica\b",
    r"\bescribe\b",
)


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
    #  Visibilidad estricta de botones                                   #
    # ------------------------------------------------------------------ #

    def _solicita_confirmacion(self, respuesta: str) -> bool:
        """
        Determina si el cierre o la última oración de la respuesta contiene una
        pregunta cerrada de verificación/confirmación que requiera botones Sí/No.

        Lógica:
        - Si no contiene signos de interrogación, retorna False.
        - Si contiene interrogativos abiertos (¿qué, cómo, cuál, etc.), retorna False.
        - De lo contrario, al ser una pregunta de verificación técnica, retorna True.
        """
        if not respuesta or not respuesta.strip():
            return False

        coincidencias = re.findall(r"¿([^?]+)\?", respuesta)
        if coincidencias:
            ultima_pregunta = coincidencias[-1].strip().lower()
        else:
            lineas_con_pregunta = [
                linea.strip().lower()
                for linea in respuesta.splitlines()
                if "?" in linea
            ]
            if not lineas_con_pregunta:
                return False
            ultima_pregunta = lineas_con_pregunta[-1]

        # Si es una pregunta abierta que invita a describir o ingresar datos
        if any(
            re.search(patron, ultima_pregunta)
            for patron in PATRONES_PREGUNTA_ABIERTA
        ):
            return False

        # Si no fue excluida por interrogativo abierto, es una pregunta cerrada de confirmación
        return True

    # ------------------------------------------------------------------ #
    #  Ejecución resiliente de llamadas a Gemini                         #
    # ------------------------------------------------------------------ #

    async def _invocar_llm_con_reintentos(
        self,
        operacion: Callable[[], Awaitable[Any]],
        descripcion: str,
        validador: Optional[Callable[[Any], bool]] = None
    ) -> Any:
        """
        Ejecuta una operación del LLM con timeout por intento y reintentos.

        Cada intento se acota con REQUEST_TIMEOUT_SECONDS para que una conexión
        colgada no bloquee el procesamiento. Si todos los intentos fallan,
        propaga la última excepción para que el llamador decida el mensaje final.
        """
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
                ultimo_error = RuntimeError(
                    f"{descripcion}: el LLM devolvió una respuesta vacía"
                )
                logger.warning(
                    "[RAG LLM] Intento %d/%d de %s devolvió una respuesta vacía.",
                    intento, intentos_totales, descripcion
                )
            except asyncio.TimeoutError:
                ultimo_error = asyncio.TimeoutError(
                    f"{descripcion}: excedió {settings.REQUEST_TIMEOUT_SECONDS}s"
                )
                logger.warning(
                    "[RAG LLM TIMEOUT] Intento %d/%d de %s excedió %.1fs.",
                    intento, intentos_totales, descripcion,
                    settings.REQUEST_TIMEOUT_SECONDS
                )
            except Exception as error:
                ultimo_error = error
                logger.warning(
                    "[RAG LLM RETRY] Intento %d/%d de %s falló: %s",
                    intento, intentos_totales, descripcion, error
                )

            if intento < intentos_totales:
                # Backoff progresivo y acotado antes del siguiente intento.
                await asyncio.sleep(0.8 * intento)

        if ultimo_error:
            raise ultimo_error
        raise RuntimeError(f"{descripcion}: no se obtuvo respuesta del LLM")

    # ------------------------------------------------------------------ #
    #  Recuperación de Contexto Vectorial                                #
    # ------------------------------------------------------------------ #

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        """Recupera fragmentos de manuales técnicos con umbral de similitud estricto."""
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
                logger.info(
                    "[RAG] Fragmento descartado por similitud insuficiente: score=%.3f (umbral=%.2f)",
                    score, settings.MIN_SIMILARITY_SCORE
                )
                continue
            payload = getattr(resultado, "payload", {}) or {}
            contenido = payload.get("page_content")
            if contenido:
                contexto.append(contenido)

        return "\n\n".join(contexto) if contexto else None

    # ------------------------------------------------------------------ #
    #  Ciclo principal de respuesta                                      #
    # ------------------------------------------------------------------ #

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> tuple[str, bool]:
        """
        Orquesta el ciclo completo de RAG con Gemini y persistencia atómica.

        Retorna:
            tuple[str, bool]: (respuesta_texto, mostrar_botones). El flag sólo
            es True cuando hay documentación y la respuesta espera confirmación
            de un paso del manual.
        """
        logger.info(
            "[RAG] Consulta recibida — usuario: %s (%s): %s",
            user_name, conversation_id, pregunta
        )

        # Imagen sin texto: nunca debe caer en el saludo inicial.
        if image_base64 and not (pregunta or "").strip():
            pregunta = "Analiza esta imagen y dime cuál es el problema."

        title = pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        await asyncio.to_thread(
            self.conversation_repo.crear_o_actualizar_conversacion,
            conversation_id, user_id, user_name, title
        )

        # — Análisis de imagen adjunta —
        descripcion_imagen = ""
        if image_base64:
            try:
                descripcion_imagen = await self._invocar_llm_con_reintentos(
                    lambda: self.llm_service.extraer_descripcion_imagen(image_base64),
                    "análisis de imagen"
                )
            except Exception as error:
                logger.warning(
                    "[RAG LLM] No se pudo describir la imagen tras los reintentos: %s",
                    error
                )
                descripcion_imagen = ""

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

        # — Detección de cierre exitoso de incidente (MÁXIMA PRIORIDAD) —
        if any(frase in pregunta_limpia for frase in FRASES_EXITO):
            logger.info("[RAG] Cierre de incidente detectado para: %s", user_name)
            despedida = (
                f"¡Excelente, {user_name}! 🎉 Me alegra mucho que hayas podido resolver el problema. "
                "Si en el futuro tienes otra consulta técnica, aquí estaré para ayudarte. "
                "¡Que tengas un excelente día!"
            )
            await asyncio.to_thread(
                self.conversation_repo.limpiar_estado,
                conversation_id
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
        # Con una imagen adjunta jamás se responde con el saludo genérico.
        if (
            pregunta_normalizada in SALUDOS
            and not historial
            and not image_base64
        ):
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
            # Extraer términos clave limpios para el vector search evitando dilución de embeddings
            terminos_limpios = (
                descripcion_imagen
                .replace("Sistema:", "")
                .replace("Error:", "")
                .replace("1.", "")
                .replace("2.", "")
                .replace("3.", "")
                .strip()
            )
            palabras = terminos_limpios.split()[:25]
            consulta_busqueda = " ".join(palabras)
        else:
            consulta_busqueda = pregunta

        contexto: Optional[str] = None
        documentacion_encontrada = False
        if consulta_busqueda:
            contexto = await self.recuperar_contexto(pregunta=consulta_busqueda)

        if contexto:
            documentacion_encontrada = True
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, None, contexto
            )
        elif last_context:
            logger.info("[RAG] Reutilizando manual activo guardado en base de datos.")
            contexto = last_context
            documentacion_encontrada = True
        elif es_respuesta_corta and historial:
            logger.info("[RAG] Reconstruyendo contexto desde historial previo...")
            mensajes_previos = [m.content for m in historial if m.role == "user"]
            if mensajes_previos:
                contexto = await self.recuperar_contexto(pregunta=mensajes_previos[-1])
                if contexto:
                    documentacion_encontrada = True
                    await asyncio.to_thread(
                        self.conversation_repo.actualizar_estado_conversacion,
                        conversation_id, None, contexto
                    )
        elif image_base64:
            contexto = (
                f"El usuario adjuntó una captura de pantalla. Diagnóstico visual en pantalla: {descripcion_imagen}. "
                "Examina directamente la imagen adjunta para guiar al usuario según el ecosistema correspondiente."
            )
            documentacion_encontrada = True

        # — Construir prompt y generar respuesta con reintentos —
        pregunta_efectiva = pregunta
        if image_base64 and descripcion_imagen:
            if "analiza esta imagen" in pregunta.lower() or len(pregunta.split()) <= 4:
                pregunta_efectiva = (
                    f"Analiza la captura de pantalla adjunta. En la pantalla se visualiza: {descripcion_imagen}. "
                    "Diagnostica el problema técnico y entrégame el primer paso de solución."
                )
            else:
                pregunta_efectiva = (
                    f"{pregunta}\n"
                    f"[Detalles visuales observados en pantalla: {descripcion_imagen}]"
                )

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
            # Último recurso: ya se agotaron todos los intentos y el backoff.
            logger.error(
                "[RAG LLM FATAL] Se agotaron los %d intentos con el LLM: %s",
                settings.MAX_RETRIES_LLM + 1, error
            )
            return MENSAJE_ERROR_RESCATE, False

        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "user", mensaje_usuario_bd
        )
        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "assistant", respuesta
        )

        # Visibilidad de botones Sí / No:
        # Se muestran cuando la respuesta termina en una pregunta cerrada de validación/confirmación.
        mostrar_botones = self._solicita_confirmacion(respuesta)

        logger.info(
            "[RAG] Respuesta lista. mostrar_botones=%s (documentacion=%s)",
            mostrar_botones, documentacion_encontrada
        )
        return respuesta, mostrar_botones