import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from app.prompts.system_prompt import (
    construir_prompt,
    construir_prompt_bienvenida,
    construir_prompt_clasificador,
)
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.interfaces.vector_repository import IVectorRepository
from app.services.interfaces.llm_service import ILLMService
from app.core.config import settings
from app.utils.format_utils import limpiar_razonamiento_interno

logger = logging.getLogger(__name__)

BOOST_MANUAL_ACTIVO = 0.08


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
    #  Utilidades de Extracción y Clasificación con LLM                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extraer_manuales_activos(last_context: Optional[str]) -> Set[str]:
        """Extrae el conjunto de nombres de manuales presentes en el último contexto guardado."""
        if not last_context:
            return set()
        encontrados = re.findall(r"DOCUMENTO / MANUAL:\s*(.+)", last_context)
        return {doc.strip() for doc in encontrados if doc.strip()}

    @staticmethod
    def _extraer_tipo_pregunta(respuesta_cruda: str) -> str:
        """
        Extrae la clasificación TIPO_PREGUNTA (CERRADA o ABIERTA) emitida dentro
        del bloque <razonamiento> antes de limpiarlo.
        """
        if not respuesta_cruda:
            return "cerrada"
        match = re.search(
            r"TIPO_PREGUNTA\s*:\s*(CERRADA|ABIERTA)",
            respuesta_cruda,
            flags=re.IGNORECASE
        )
        if match and match.group(1).upper() == "ABIERTA":
            return "abierta"
        return "cerrada"

    async def _clasificar_intencion(
        self,
        pregunta: str,
        historial: list,
        last_context: Optional[str],
        root_issue: Optional[str],
        tiene_imagen: bool = False
    ) -> Dict[str, Any]:
        """
        Delega al LLM la clasificación semántica de la intención del usuario
        para enrutar sin depender de listas estáticas de palabras.
        """
        if tiene_imagen:
            return {
                "intencion": "NUEVA_CONSULTA_TECNICA",
                "reconsultar_qdrant": True,
                "consultas_busqueda": [pregunta],
            }

        ultimo_asistente = None
        for msg in reversed(historial):
            rol = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else "")
            if rol == "assistant":
                ultimo_asistente = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
                break

        prompt_cls = construir_prompt_clasificador(
            pregunta=pregunta,
            tiene_historial=bool(historial),
            tiene_contexto_activo=bool(last_context),
            root_issue=root_issue,
            ultimo_mensaje_asistente=ultimo_asistente
        )

        salida_cruda = await self.llm_service.generar_respuesta(prompt_cls)

        try:
            salida_limpia = limpiar_razonamiento_interno(salida_cruda)
            match_json = re.search(r"\{.*\}", salida_limpia, flags=re.DOTALL)
            if match_json:
                data = json.loads(match_json.group(0))
                intencion = str(data.get("intencion", "NUEVA_CONSULTA_TECNICA")).strip().upper()
                reconsultar = bool(data.get("reconsultar_qdrant", False))
                consultas = data.get("consultas_busqueda") or [pregunta]
                if not isinstance(consultas, list) or not consultas:
                    consultas = [pregunta]
                consultas = [str(c).strip() for c in consultas[:2] if str(c).strip()]
                return {
                    "intencion": intencion,
                    "reconsultar_qdrant": reconsultar,
                    "consultas_busqueda": consultas or [pregunta],
                }
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as err:
            logger.warning("[RAG ROUTER] Fallback a consulta técnica por error parseando intención: %s", err)

        return {
            "intencion": "NUEVA_CONSULTA_TECNICA",
            "reconsultar_qdrant": True,
            "consultas_busqueda": [pregunta],
        }

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

        if bloquear_manual_top:
            top_payload = getattr(resultados[0], "payload", {}) or {}
            doc_objetivo = top_payload.get("document_name", "")
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
        image_base64: Optional[str] = None,
        space_name: Optional[str] = None,
        thread_name: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Orquesta el ciclo completo de RAG con Gemini y persistencia atómica.
        Retorna (respuesta_texto, modo_botones) donde modo_botones es 'cerrada', 'abierta' o 'ninguno'.
        """
        logger.info(
            "[RAG] Consulta recibida — usuario: %s (%s): %s",
            user_name, conversation_id, pregunta
        )

        # — Validar expiración por inactividad —
        expirada = await asyncio.to_thread(
            self.conversation_repo.expirar_conversacion_si_inactiva,
            conversation_id,
            settings.CONVERSATION_TIMEOUT_MINUTES
        )
        prefijo_inactividad = (
            "🕒 *Tu conversación anterior se reinició por tiempo de inactividad.*\n\n"
            if expirada else ""
        )

        # — Leer historial y estado previo sin ensuciar la BD todavía —
        historial = await asyncio.to_thread(
            self.conversation_repo.obtener_historial, conversation_id, 8
        )
        estado_conv = await asyncio.to_thread(
            self.conversation_repo.obtener_estado_conversacion, conversation_id
        )
        root_issue = estado_conv.root_issue
        last_context = estado_conv.last_context
        manuales_activos = self._extraer_manuales_activos(last_context)

        # — Clasificar intención mediante LLM —
        ruta = await self._clasificar_intencion(
            pregunta=pregunta,
            historial=historial,
            last_context=last_context,
            root_issue=root_issue,
            tiene_imagen=bool(image_base64)
        )
        intencion = ruta["intencion"]
        logger.info("[RAG ROUTER] Intención=%s | Reconsultar=%s | Consultas=%s", intencion, ruta["reconsultar_qdrant"], ruta["consultas_busqueda"])

        # 1. Confirmación o respuesta corta suelta cuando NO hay conversación activa
        if intencion == "CONFIRMACION_SIN_CONTEXTO":
            aviso = (
                prefijo_inactividad
                or "Todavía no tenemos un tema o consulta activa. "
            )
            return (
                f"{aviso}Por favor, indícame en qué proceso, sistema o inconveniente te puedo ayudar.",
                "ninguno"
            )

        # Asegurar registro de conversación para flujos con estado
        title = pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        await asyncio.to_thread(
            self.conversation_repo.crear_o_actualizar_conversacion,
            conversation_id, user_id, user_name, title
        )

        # 2. Cierre exitoso del caso
        if intencion == "CIERRE_EXITOSO":
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
            return f"{prefijo_inactividad}{despedida}", "ninguno"

        # 3. Bienvenida dinámica o consulta sobre capacidades reales
        if intencion == "SALUDO_O_CAPACIDADES":
            manuales_disponibles = await asyncio.to_thread(
                self.vector_repo.listar_documentos_indexados
            )
            prompt_bienvenida = construir_prompt_bienvenida(
                usuario=user_name,
                manuales_disponibles=manuales_disponibles,
                correo_ti=settings.TI_HWI_EMAIL,
                tiene_historial=bool(historial)
            )
            respuesta_cruda = await self.llm_service.generar_respuesta(prompt_bienvenida)
            respuesta_saludo = limpiar_razonamiento_interno(respuesta_cruda)
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", pregunta
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_saludo
            )
            return f"{prefijo_inactividad}{respuesta_saludo}", "ninguno"

        # — Análisis de imagen adjunta —
        descripcion_imagen = ""
        if image_base64:
            descripcion_imagen = await self.llm_service.extraer_descripcion_imagen(image_base64)

        mensaje_usuario_bd = (
            f"[Imagen: {descripcion_imagen}] {pregunta}".strip()
            if (image_base64 and descripcion_imagen)
            else f"[Imagen adjunta] {pregunta}".strip() if image_base64 else pregunta
        )

        # 4. Gestión de Root Issue y Recuperación de Contexto
        es_seguimiento = (intencion == "SEGUIMIENTO_ACTIVO")

        if not es_seguimiento:
            # Si es una nueva consulta técnica (o cambio de tema), actualizar objetivo raíz y liberar bloqueo viejo
            root_issue = f"{pregunta} {descripcion_imagen}".strip()
            manuales_activos = set()
        elif not root_issue:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()

        contexto: Optional[str] = None
        reutilizando_contexto = False

        if es_seguimiento and last_context and not ruta["reconsultar_qdrant"]:
            logger.info("[RAG] Seguimiento activo: reutilizando manual bloqueado en MySQL sin re-consultar Qdrant.")
            contexto = last_context
            reutilizando_contexto = True
        else:
            sub_consultas = ruta["consultas_busqueda"]
            if descripcion_imagen and len(sub_consultas) == 1:
                sub_consultas = [f"{sub_consultas[0]} {descripcion_imagen}".strip()]

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
                    pregunta=sub_consultas[0],
                    manuales_activos=manuales_activos
                )

        # Encadenamiento automático cuando un manual referencia otro procedimiento
        if contexto and any(
            ref in contexto.lower()
            for ref in ("manual específico", "resincronización", "desbloqueo de aplicaciones")
        ) and "access.whirlpool.com/wpass" not in contexto.lower():
            logger.info("[RAG] Referencia cruzada detectada. Recuperando manual complementario de WPASS...")
            contexto_extra = await self.recuperar_contexto(
                pregunta="resincronización y desbloqueo de aplicaciones en WPASS",
                limite=3
            )
            if contexto_extra:
                contexto = f"{contexto}\n\n{contexto_extra}"

        # Actualizar estado de conversación si se recuperó contexto nuevo
        if contexto and not reutilizando_contexto:
            await asyncio.to_thread(
                self.conversation_repo.actualizar_estado_conversacion,
                conversation_id, root_issue, contexto
            )

        # — Sin contexto disponible: derivación directa al Encargado de TI sin inventar —
        if not contexto:
            respuesta_sin_doc = (
                f"No tengo conocimiento ni información oficial en mi base de datos sobre **{pregunta}**, "
                "por lo que no puedo darte un procedimiento para este caso.\n\n"
                f"Por favor, comunícate directamente con el **Encargado de TI de HWI** al correo **{settings.TI_HWI_EMAIL}** para que te brinden soporte"
                " (o si se trata de una falla o solicitud en un sistema de Whirlpool como SAP, WPASS o Citrix, puedes gestionar un ticket en **ServiceNow**: https://whirlpool.service-now.com/sp)."
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "user", mensaje_usuario_bd
            )
            await asyncio.to_thread(
                self.conversation_repo.agregar_mensaje,
                conversation_id, user_id, user_name, "assistant", respuesta_sin_doc
            )
            return f"{prefijo_inactividad}{respuesta_sin_doc}", "ninguno"

        # — Construir prompt y generar respuesta —
        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial,
            root_issue=root_issue,
            correo_ti=settings.TI_HWI_EMAIL
        )

        respuesta_cruda = await self.llm_service.generar_respuesta(prompt, image_base64)
        modo_botones = self._extraer_tipo_pregunta(respuesta_cruda)
        respuesta = limpiar_razonamiento_interno(respuesta_cruda)
        logger.debug("[COT INTERNO] (botones=%s) %s", modo_botones, respuesta_cruda)

        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "user", mensaje_usuario_bd
        )
        await asyncio.to_thread(
            self.conversation_repo.agregar_mensaje,
            conversation_id, user_id, user_name, "assistant", respuesta
        )

        logger.info("[RAG] Respuesta generada y persistida exitosamente (modo_botones=%s).", modo_botones)
        return f"{prefijo_inactividad}{respuesta}", modo_botones