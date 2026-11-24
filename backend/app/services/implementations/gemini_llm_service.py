import asyncio
import logging
from typing import List, Optional

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from app.core.config import settings
from app.services.interfaces.llm_service import ILLMService

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 20.0
EMBEDDING_TIMEOUT_SECONDS = 15.0


class GeminiLLMService(ILLMService):
    """
    Implementación de ILLMService con failover automático entre modelos Gemini
    ante errores transitorios de alta demanda (503/504/429) o timeouts.
    """

    def __init__(self) -> None:
        self._embedding_model = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY or None
        )
        modelos_cadena = [settings.CHAT_MODEL] + settings.fallback_models_list
        self._llms: list[tuple[str, ChatGoogleGenerativeAI]] = [
            (nombre_modelo, self._crear_cliente_chat(nombre_modelo))
            for nombre_modelo in modelos_cadena
        ]
        logger.info(
            "[GeminiLLMService] Inicializado con cadena de modelos=%s y embeddings='%s'.",
            modelos_cadena, settings.EMBEDDING_MODEL
        )

    @staticmethod
    def _crear_cliente_chat(model_name: str) -> ChatGoogleGenerativeAI:
        kwargs: dict = {
            "model": model_name,
            "max_retries": 0,
            "timeout": 18.0,
            "google_api_key": settings.GOOGLE_API_KEY or None,
        }
        if "3.5" not in model_name:
            kwargs["temperature"] = 0.1
            kwargs["top_p"] = 0.9
        return ChatGoogleGenerativeAI(**kwargs)

    @staticmethod
    def _es_error_conmutable(exc: Exception) -> bool:
        texto = str(exc).upper()
        return any(
            token in texto
            for token in (
                "503", "UNAVAILABLE",
                "504", "DEADLINE_EXCEEDED",
                "429", "RESOURCE_EXHAUSTED",
                "404", "NOT_FOUND",
                "TIMEOUT", "DISCONNECTED"
            )
        )

    async def _invocar_con_fallback(self, mensaje: HumanMessage):
        ultimo_error: Optional[Exception] = None
        for idx, (nombre_modelo, cliente_llm) in enumerate(self._llms):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(cliente_llm.invoke, [mensaje]),
                    timeout=LLM_TIMEOUT_SECONDS
                )
            except Exception as exc:
                ultimo_error = exc
                hay_siguiente = idx < len(self._llms) - 1
                if hay_siguiente and self._es_error_conmutable(exc):
                    logger.warning(
                        "[GeminiLLMService] Modelo '%s' no disponible (%s). Conmutando a '%s'...",
                        nombre_modelo, type(exc).__name__, self._llms[idx + 1][0]
                    )
                    continue
                raise

        if ultimo_error:
            raise ultimo_error

    # ------------------------------------------------------------------ #
    #  ILLMService — Embeddings                                            #
    # ------------------------------------------------------------------ #

    async def generar_embedding(self, texto: str) -> List[float]:
        """Genera vector de embeddings sin bloquear el event loop."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._embedding_model.embed_query, texto),
                timeout=EMBEDDING_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Tiempo de espera agotado ({EMBEDDING_TIMEOUT_SECONDS}s) al generar embedding en Gemini."
            ) from exc

    # ------------------------------------------------------------------ #
    #  ILLMService — Análisis de Imagen                                   #
    # ------------------------------------------------------------------ #

    async def extraer_descripcion_imagen(self, image_base64: str) -> str:
        """Extrae términos técnicos clave de la captura mediante LLM multimodal."""
        if not image_base64:
            return ""

        try:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            prompt_extraccion = (
                "Actúa como un analizador técnico de TI. Observa esta imagen y responde en 1 sola línea breve: "
                "el nombre del software o sistema involucrado y el mensaje o código de error textual exacto."
            )
            mensaje = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_extraccion},
                    {"type": "image_url", "image_url": {"url": image_data_uri}}
                ]
            )

            res = await self._invocar_con_fallback(mensaje)

            texto_respuesta = res.content
            if isinstance(texto_respuesta, list):
                texto_respuesta = "".join(
                    b if isinstance(b, str) else b.get("text", "") for b in texto_respuesta
                )
            descripcion = str(texto_respuesta).strip()
            logger.info("[GeminiLLMService] Términos técnicos extraídos de imagen: %s", descripcion)
            return descripcion
        except Exception as exc:
            logger.warning("[GeminiLLMService] No se pudo analizar la imagen: %s", exc)
            return ""

    # ------------------------------------------------------------------ #
    #  ILLMService — Generación de Respuesta                              #
    # ------------------------------------------------------------------ #

    async def generar_respuesta(self, prompt: str, image_base64: Optional[str] = None) -> str:
        """Genera la respuesta del asistente con failover automático entre modelos."""
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

        try:
            respuesta_llm = await self._invocar_con_fallback(mensaje_llm)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Tiempo de espera agotado ({LLM_TIMEOUT_SECONDS}s) esperando respuesta de Gemini."
            ) from exc

        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = [b if isinstance(b, str) else b.get("text", "") for b in contenido]
            return "".join(partes)
        return str(contenido)