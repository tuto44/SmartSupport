import asyncio
import logging
import re
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

# Expresiones que indican que el usuario confirmó el cierre exitoso del incidente.
# Cuando se detectan, se limpia el estado y se retorna una despedida sin más pasos técnicos.
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

# Patrones para clasificar preguntas abiertas (no deben mostrar botones Sí / No)
PATRONES_PREGUNTAS_ABIERTAS = [
    r"¿?\s*qué\b", r"¿?\s*que\b", r"¿?\s*cuál\b", r"¿?\s*cual\b",
    r"¿?\s*cuáles\b", r"¿?\s*cuales\b", r"¿?\s*cómo\b", r"¿?\s*como\b",
    r"¿?\s*dónde\b", r"¿?\s*donde\b", r"¿?\s*por\s+qué\b", r"¿?\s*por\s+que\b",
    r"¿?\s*cuándo\b", r"¿?\s*cuando\b", r"¿?\s*quién\b", r"¿?\s*quien\b",
    r"\bdescribe\b", r"\bingresa\b", r"\bindica\b", r"\bescribe\b"
]

# Patrones para clasificar preguntas cerradas que esperan confirmación binaria (Sí / No)
PATRONES_PREGUNTAS_CERRADAS = [
    r"¿?\s*lograste", r"¿?\s*pudiste", r"¿?\s*te\s+funcion[oó]", r"¿?\s*te\s+sirvi[oó]",
    r"¿?\s*te\s+aparece", r"¿?\s*se\s+muestra", r"¿?\s*lo\s+visualizas", r"¿?\s*la\s+visualizas",
    r"¿?\s*ya\s+carg[oó]", r"¿?\s*ya\s+conect[oó]", r"¿?\s*contin[uú]a\s+el\s+error",
    r"¿?\s*persiste\s+la\s+falla", r"¿?\s*persiste\s+el\s+error", r"¿?\s*persiste\s+el\s+problema",
    r"¿?\s*deseas\s+que\s+te\s+gu[ií]e", r"¿?\s*quieres\s+intentar", r"¿?\s*funcion[oó]",
    r"¿?\s*pudiste\s+ingresar", r"¿?\s*lograste\s+entrar", r"¿?\s*se\s+solucion[oó]"
]


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
    #  Evaluación de Pregunta Cerrada vs Abierta                          #
    # ------------------------------------------------------------------ #

    def evaluar_requiere_sino(self, texto_respuesta: str) -> bool:
        """
        Determina si el cierre o la última oración de la respuesta contiene una
        pregunta cerrada de verificación/confirmación que deba presentar botones Sí/No.

        Si es pregunta abierta (¿Qué, Cómo, Cuál, etc.) o informativa, retorna False.
        """
        if not texto_respuesta or not texto_respuesta.strip():
            return False

        # Extraer las últimas oraciones/líneas relevantes del mensaje
        lineas = [line.strip() for line in texto_respuesta.strip().split("\n") if line.strip()]
        if not lineas:
            return False

        # Tomar la última porción o encontrar la última pregunta (entre ¿ y ?)
        ultimo_tramo = lineas[-1].lower()
        coincidencias_preguntas = re.findall(r"¿([^?]+)\?", texto_respuesta.lower())
        ultima_pregunta = coincidencias_preguntas[-1] if coincidencias_preguntas else ultimo_tramo

        # 1. Regla de exclusión: si contiene interrogativos abiertos, descartar
        for patron in PATRONES_PREGUNTAS_ABIERTAS:
            if re.search(patron, ultima_pregunta):
                logger.info("[RAG SINO] Pregunta abierta detectada ('%s'). mostrar_sino=False", patron)
                return False

        # 2. Regla de inclusión: si coincide con patrones cerrados específicos
        for patron in PATRONES_PREGUNTAS_CERRADAS:
            if re.search(patron, ultima_pregunta) or re.search(patron, ultimo_tramo):
                logger.info("[RAG SINO] Pregunta cerrada detectada ('%s'). mostrar_sino=True", patron)
                return True

        # 3. Heurística general para preguntas interrogativas cerradas
        # Si termina en signo de interrogación o contiene pregunta sin pronombres interrogativos abiertos
        if "?" in ultimo_tramo or "¿" in ultimo_tramo:
            # Si no fue clasificada como abierta arriba, y es una pregunta corta de validación
            if any(verbo in ultima_pregunta for verbo in ["pudiste", "funciona", "sirve", "aparece", "muestra", "resuelto", "correcto", "listo"]):
                return True

        return False

    # ------------------------------------------------------------------ #
    #  Recuperación de Contexto Vectorial                                  #
    # ------------------------------------------------------------------ #

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS
    ) -> Optional[str]:
        """Recupera fragmentos de manuales técnicos con umbral de similitud estricto."""
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
            # Solo se incluyen fragmentos que superen el umbral MIN_SIMILARITY_SCORE (0.65).
            # Fragmentos con score menor se descartan para evitar alucinaciones.
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
    #  Ciclo principal de respuesta                                        #
    # ------------------------------------------------------------------ #

    async def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: Optional[str] = None
    ) -> tuple[str, bool, bool]:
        """
        Orquesta el ciclo completo de RAG con Gemini y persistencia atómica.

        Retorna:
            tuple[str, bool, bool]: (respuesta_texto, mostrar_sino, mostrar_cambiar_tema)
        """
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
            for intento in range(settings.MAX_RETRIES_LLM + 1):
                try:
                    descripcion_imagen = await self.llm_service.extraer_descripcion_imagen(image_base64)
                    break
                except Exception as e:
                    logger.warning("[RAG LLM RETRY] Reintento %d extracción imagen falló: %s", intento, e)
                    if intento == settings.MAX_RETRIES_LLM:
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
        # Si el usuario confirma que el problema se resolvió, se limpia el estado
        # y se retorna una despedida cordial sin botones (mostrar_sino=False, mostrar_cambiar_tema=False).
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
            return despedida, False, False

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
            return respuesta_saludo, False, True

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
            mensajes_previos = [m.content for m in historial if m.role == "user"]
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

        # — Sin contexto disponible: derivación formal —
        if not contexto:
            respuesta_sin_doc = (
                "⚠️ No encontré un procedimiento específico para tu consulta en la base de conocimiento "
                "oficial del Asistente TI.\n\n"
                "Para obtener soporte especializado, te recomiendo:\n"
                "1. 📋 Generar un ticket en **My Whirlpool** > *IT Service Catalog* > **Something's Broken**\n"
                "2. 📞 Contactar a la **Mesa de Ayuda Nivel 2** directamente\n\n"
                "Un agente de soporte especializado podrá asistirte con este requerimiento."
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", mensaje_usuario_bd
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_sin_doc
            )
            return respuesta_sin_doc, False, True

        # — Construir prompt y generar respuesta con reintentos —
        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial,
            root_issue=root_issue
        )

        respuesta = ""
        ultimo_error: Optional[Exception] = None
        for intento in range(settings.MAX_RETRIES_LLM + 1):
            try:
                respuesta = await self.llm_service.generar_respuesta(prompt, image_base64)
                if respuesta and respuesta.strip():
                    break
            except Exception as e:
                ultimo_error = e
                logger.warning(
                    "[RAG LLM RETRY] Intento %d de generación falló: %s",
                    intento + 1, e
                )
                if intento < settings.MAX_RETRIES_LLM:
                    await asyncio.sleep(0.8 * (intento + 1))

        if not respuesta or not respuesta.strip():
            if ultimo_error:
                logger.error("[RAG LLM FATAL] Se agotaron los reintentos con el LLM: %s", ultimo_error)
            raise RuntimeError("Fallo temporal al comunicarse con el modelo de IA tras varios reintentos.")

        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "user", mensaje_usuario_bd
        )
        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "assistant", respuesta
        )

        # Evaluación dinámica de botones interactivos
        mostrar_sino = self.evaluar_requiere_sino(respuesta)
        mostrar_cambiar_tema = True

        logger.info(
            "[RAG] Respuesta lista. mostrar_sino=%s, mostrar_cambiar_tema=%s",
            mostrar_sino, mostrar_cambiar_tema
        )
        return respuesta, mostrar_sino, mostrar_cambiar_tema
