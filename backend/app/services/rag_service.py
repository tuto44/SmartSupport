import asyncio
import logging
import re
from typing import List, Optional, Set

from app.prompts.system_prompt import construir_prompt
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.services.interfaces.llm_service import ILLMService
from app.core.config import settings
from app.utils.format_utils import limpiar_razonamiento_interno

logger = logging.getLogger(__name__)

BOOST_MANUAL_ACTIVO = 0.08

SALUDOS = {
    "hola", "buenas", "buen dia", "buen día", "buenos dias", "buenos días",
    "buenas tardes", "buenas noches", "hey", "saludos", "hola!", "que tal", "qué tal", "iniciar"
}

RESPUESTAS_SEGUIMIENTO = {
    "si", "sí", "no", "ya", "ya lo hice", "listo", "no funcionó",
    "no me deja", "ok", "vale", "ya está", "ya termine", "ya terminé",
    "funciono", "funcionó", "siguiente", "continuar", "sigue igual",
    "ya entré", "ya entre", "ya abre", "ya carga", "ya cargó",
    "ya pude", "ya pude entrar"
}

FRASES_RECUPERACION = {
    "ya tengo internet", "ya cargo", "ya cargó", "ya navega",
    "ya volvio el internet", "ya volvió el internet", "ya conecto el wifi",
    "ya tengo red", "ya dio ip", "ya conecto internet"
}

FRASES_EXITO = {
    "ya funcionó", "ya funciono", "ya sirvió", "ya sirvio",
    "ya quedó", "ya quedo",
    "listo ya quedó", "listo ya quedo", "perfecto gracias",
    "solucionado", "gracias funciono", "gracias funcionó",
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
    #  Utilidades de Extracción y Descomposición                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extraer_manuales_activos(last_context: Optional[str]) -> Set[str]:
        """Extrae el conjunto de nombres de manuales presentes en el último contexto guardado."""
        if not last_context:
            return set()
        encontrados = re.findall(r"DOCUMENTO / MANUAL:\s*(.+)", last_context)
        return {doc.strip() for doc in encontrados if doc.strip()}

    @staticmethod
    def _descomponer_consulta_compuesta(consulta: str) -> List[str]:
        """
        Divide consultas compuestas con problemas dobles en un máximo de 2 sub-consultas
        de al menos 2 palabras cada una. Solo opera si la consulta tiene >= 6 palabras y no
        es una respuesta corta de seguimiento.
        """
        if not consulta:
            return []

        palabras = consulta.strip().split()
        if len(palabras) < 6:
            return [consulta.strip()]

        consulta_limpia = consulta.strip().lower()
        if consulta_limpia in RESPUESTAS_SEGUIMIENTO:
            return [consulta.strip()]

        conectores = ["y tampoco", "y además", "pero tampoco", "y no", " y ", ", "]
        for conector in conectores:
            partes = re.split(re.escape(conector), consulta, maxsplit=1, flags=re.IGNORECASE)
            if len(partes) == 2:
                sub1 = partes[0].strip()
                sub2 = partes[1].strip()
                if len(sub1.split()) >= 2 and len(sub2.split()) >= 2:
                    return [sub1, sub2]

        return [consulta.strip()]

    # ------------------------------------------------------------------ #
    #  Recuperación de Contexto Vectorial con Re-ranking                 #
    # ------------------------------------------------------------------ #

    async def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = settings.TOP_K_RESULTS,
        manuales_activos: Optional[Set[str]] = None,
        bloquear_manual_top: bool = True
    ) -> Optional[str]:
        """
        Recupera fragmentos de manuales técnicos aplicando umbral mínimo de similitud,
        re-ranking con boost por afinidad al manual activo y bloqueo de manual único.
        """
        logger.info("[RAG] Búsqueda vectorial para: '%s' (manuales activos: %s)", pregunta, manuales_activos)
        candidatos_limite = max(limite * 2, 8) if manuales_activos else limite

        embedding = await self.llm_service.generar_embedding(pregunta)
        resultados = await asyncio.to_thread(
            self.vector_repo.buscar_similares, embedding, candidatos_limite
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

        candidatos_validos = []
        for resultado in resultados:
            score_base = getattr(resultado, "score", 0.0)
            if score_base < settings.MIN_SIMILARITY_SCORE:
                continue
            payload = getattr(resultado, "payload", {}) or {}
            contenido = payload.get("page_content")
            if not contenido:
                continue

            doc_name = payload.get("document_name")
            score_ajustado = score_base
            if manuales_activos and doc_name and doc_name in manuales_activos:
                score_ajustado += BOOST_MANUAL_ACTIVO

            candidatos_validos.append((score_ajustado, contenido, doc_name))

        if not candidatos_validos:
            return None

        # Single-Manual Lock: restringir todos los fragmentos al documento ganador
        if bloquear_manual_top:
            top_payload = getattr(resultados[0], "payload", {}) or {}
            doc_objetivo = top_payload.get("document_name", "")
            # Si hay exactamente 1 manual activo y está entre los válidos, forzarlo
            if manuales_activos and len(manuales_activos) == 1:
                nombre_activo = next(iter(manuales_activos))
                nombres_validos = {c[2] for c in candidatos_validos if c[2]}
                if nombre_activo in nombres_validos:
                    doc_objetivo = nombre_activo
            if doc_objetivo:
                candidatos_bloqueados = [
                    (s, c, d) for s, c, d in candidatos_validos if d == doc_objetivo
                ]
                if candidatos_bloqueados:
                    candidatos_validos = candidatos_bloqueados
                    logger.info("[RAG] Single-Manual Lock activo: usando solo '%s'", doc_objetivo)

        candidatos_validos.sort(key=lambda item: item[0], reverse=True)
        seleccionados = [item[1] for item in candidatos_validos[:limite]]
        return "\n\n".join(seleccionados) if seleccionados else None

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
        manuales_activos = self._extraer_manuales_activos(last_context)

        pregunta_limpia = pregunta.strip().lower()
        pregunta_normalizada = "".join(
            c for c in pregunta_limpia if c.isalnum() or c.isspace()
        ).strip()

        # — Detección de cierre exitoso de incidente —
        if any(frase in pregunta_limpia for frase in FRASES_EXITO):
            logger.info("[RAG] Cierre de incidente detectado para: %s", user_name)
            despedida = (
                f"¡Excelente, {user_name}! 🎉 Me alegra mucho que hayas podido resolver el inconveniente. "
                "Si en el futuro requieres soporte con algún otro proceso o herramienta en HWI, "
                "aquí estaré para asistirte. ¡Que tengas un excelente día!"
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
                f"¡Hola, {user_name}! 👋 Soy **GABI** (*Guía y Asistencia Business Intelligent*), "
                "tu asistente virtual en HWI.\n\n"
                "Estoy aquí para acompañarte con guías paso a paso, consultas y soporte en tus procesos y "
                "herramientas (como VPN, WPASS, Citrix, SAP, accesos y gestión general).\n\n"
                "¿En qué te puedo ayudar hoy?"
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
            or any(frase in pregunta_limpia for frase in (
                "ya entré", "ya entre", "ya ingresé", "ya ingrese",
                "ya abrí", "ya abri", "ya cargó", "ya cargo", "ya pude", "listo ya"
            ))
            or (len(pregunta.split()) <= 2 and bool(historial))
            or (len(pregunta.split()) <= 6 and bool(historial) and any(
                p in pregunta_limpia for p in ("listo", "ya", "enlace", "link", "página", "pagina", "pantalla", "paso")
            ))
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

        # Reutilizar last_context directamente en seguimientos cortos (evita contaminación cruzada con Qdrant)
        contexto: Optional[str] = None
        if es_respuesta_corta and last_context and not resolvio_bloqueo:
            logger.info("[RAG] Seguimiento corto detectado: reutilizando manual activo bloqueado en MySQL sin re-consultar Qdrant.")
            contexto = last_context
        elif consulta_busqueda:
            sub_consultas = self._descomponer_consulta_compuesta(consulta_busqueda)
            if len(sub_consultas) > 1:
                logger.info("[RAG] Multi-Query paralelo detectado: %s", sub_consultas)
                tareas = [
                    self.recuperar_contexto(pregunta=sq, manuales_activos=manuales_activos)
                    for sq in sub_consultas
                ]
                resultados_contextos = await asyncio.gather(*tareas)
                fragmentos_unicos = []
                vistos = set()
                for ctx in resultados_contextos:
                    if not ctx:
                        continue
                    for fragmento in ctx.split("\n\n"):
                        frag_strip = fragmento.strip()
                        if frag_strip and frag_strip not in vistos:
                            vistos.add(frag_strip)
                            fragmentos_unicos.append(frag_strip)
                contexto = "\n\n".join(fragmentos_unicos) if fragmentos_unicos else None
            else:
                contexto = await self.recuperar_contexto(
                    pregunta=consulta_busqueda,
                    manuales_activos=manuales_activos
                )

        # Encadenamiento automático cuando un manual referencia otro procedimiento
        if contexto and any(
            ref in contexto.lower()
            for ref in ("manual específico", "resincronización", "desbloqueo de aplicaciones")
        ) and "[access.whirlpool.com/wpass](https://access.whirlpool.com/wpass)" not in contexto.lower():
            logger.info("[RAG] Referencia cruzada detectada. Recuperando manual complementario de WPASS...")
            contexto_extra = await self.recuperar_contexto(
                pregunta="resincronización y desbloqueo de aplicaciones en WPASS",
                limite=3
            )
            if contexto_extra:
                contexto = f"{contexto}\n\n{contexto_extra}"

        # Si se encontró contexto válido (nuevo, no reutilizado), actualizar el estado de la conversación
        if contexto and not (es_respuesta_corta and last_context and not resolvio_bloqueo):
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, root_issue, contexto
            )

        # — Sin contexto disponible: derivación formal —
        if not contexto:
            respuesta_sin_doc = (
                f"⚠️ Hola, {user_name}. No encontré un procedimiento o manual oficial en la base de conocimientos "
                f"relacionado con **{pregunta}**.\n\n"
                "Para avanzar con tu solicitud, te sugiero escalarla según el sistema correspondiente:\n"
                "• **Ecosistema Whirlpool** (WPASS, SAP, Citrix, cuenta Gmail): genera un ticket en el portal **ServiceNow** (https://whirlpool.service-now.com/sp) según aplique (Incidente o Requerimiento).\n"
                "• **Ecosistema HWI (Local)** (FortiClient, red local HWI, equipos locales, impresoras, dispositivos personales): contacta directamente al **Encargado de TI de HWI**."
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

        respuesta_cruda = await self.llm_service.generar_respuesta(prompt, image_base64)
        respuesta = limpiar_razonamiento_interno(respuesta_cruda)
        logger.debug("[COT INTERNO] %s", respuesta_cruda)

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
