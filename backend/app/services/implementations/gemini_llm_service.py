import asyncio
import logging
from typing import List, Optional

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from app.core.config import settings
from app.services.interfaces.llm_service import ILLMService

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 25.0
EMBEDDING_TIMEOUT_SECONDS = 15.0


class GeminiLLMService(ILLMService):
    """
    Implementación de ILLMService que delega en los modelos Gemini de Google
    a través de langchain-google-genai.

    Toda operación de red (embed_query, invoke) se ejecuta en un thread pool
    mediante asyncio.to_thread con timeout explícito para no bloquear el event loop.
    """

    def __init__(self) -> None:
        self._embedding_model = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY or None
        )
        self._llm = ChatGoogleGenerativeAI(
            model=settings.CHAT_MODEL,
            temperature=0.1,
            top_p=0.9,
            max_retries=1,
            timeout=20.0,
            google_api_key=settings.GOOGLE_API_KEY or None
        )
        logger.info(
            "[GeminiLLMService] Inicializado con modelo de chat '%s' (timeout=20s, max_retries=1) y embeddings '%s'.",
            settings.CHAT_MODEL, settings.EMBEDDING_MODEL
        )

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

            res = await asyncio.wait_for(
                asyncio.to_thread(self._llm.invoke, [mensaje]),
                timeout=LLM_TIMEOUT_SECONDS
            )

            texto_respuesta = res.content
            if isinstance(texto_respuesta, list):
                texto_respuesta = "".join(
                    b if isinstance(b, str) else b.get("text", "") for b in texto_respuesta
                )
            descripcion = str(texto_respuesta).strip()
            logger.info("[GeminiLLMService] Términos técnicos extraídos de imagen: %s", descripcion)
            return descripcion
        except Exception as exc:
            logger.warning("[GeminiLLMService] No se pudo analizar la imagen (error de red/timeout): %s", exc)
            return ""

    # ------------------------------------------------------------------ #
    #  ILLMService — Generación de Respuesta                              #
    # ------------------------------------------------------------------ #

    async def generar_respuesta(self, prompt: str, image_base64: Optional[str] = None) -> str:
        """Genera la respuesta del asistente con timeout explícito. Soporta entrada multimodal opcional."""
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
            respuesta_llm = await asyncio.wait_for(
                asyncio.to_thread(self._llm.invoke, [mensaje_llm]),
                timeout=LLM_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Tiempo de espera agotado ({LLM_TIMEOUT_SECONDS}s) esperando respuesta de Gemini."
            ) from exc

        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = [b if isinstance(b, str) else b.get("text", "") for b in contenido]
            return "".join(partes)
        return str(contenido)