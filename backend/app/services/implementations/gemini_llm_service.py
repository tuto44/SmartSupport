import asyncio
import logging
from typing import List, Optional

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from app.core.config import settings
from app.services.interfaces.llm_service import ILLMService

logger = logging.getLogger(__name__)


class GeminiLLMService(ILLMService):
    """
    Implementación de ILLMService que delega en los modelos Gemini de Google
    a través de langchain-google-genai.

    Toda operación de red (embed_query, invoke) se ejecuta en un thread pool
    mediante asyncio.to_thread para no bloquear el event loop de FastAPI.
    """

    def __init__(self) -> None:
        self._embedding_model = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY or None,
            output_dimensionality=settings.EMBEDDING_DIMENSIONS
        )
        self._llm = ChatGoogleGenerativeAI(
            model=settings.CHAT_MODEL,
            request_timeout=settings.REQUEST_TIMEOUT_SECONDS,
            google_api_key=settings.GOOGLE_API_KEY or None
        )
        logger.info(
            "[GeminiLLMService] Inicializado con modelo de chat '%s' y embeddings '%s'.",
            settings.CHAT_MODEL, settings.EMBEDDING_MODEL
        )

    # ------------------------------------------------------------------ #
    #  ILLMService — Embeddings                                          #
    # ------------------------------------------------------------------ #

    async def generar_embedding(self, texto: str) -> List[float]:
        """Genera vector de embeddings sin bloquear el event loop."""
        return await asyncio.to_thread(self._embedding_model.embed_query, texto)

    # ------------------------------------------------------------------ #
    #  ILLMService — Análisis de Imagen                                   #
    # ------------------------------------------------------------------ #

    async def extraer_descripcion_imagen(self, image_base64: str) -> str:
        """Extrae términos técnicos clave de la captura mediante LLM multimodal."""
        try:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            prompt_extraccion = (
                "Eres un especialista de soporte de TI Nivel 1. Analiza con precisión la captura o imagen adjunta:\n"
                "1. Extrae el nombre exacto de la aplicación o sistema visible (ej. SAP Logon, WPass, Citrix, GlobalProtect, FortiClient, Outlook, Windows, navegador web).\n"
                "2. Transcribe de forma textual y exacta cualquier mensaje de error, código de falla, advertencia o diálogo que aparezca en pantalla.\n"
                "3. Si no hay error explícito, resume la ventana, formulario o pantalla que visualiza el usuario.\n\n"
                "Responde de forma directa con los términos técnicos extraídos (ejemplo: 'Sistema: SAP Logon. Error: Error al conectar con el servidor 10.x.x.x WSAECONNREFUSED'), sin introducciones ni despedidas."
            )
            mensaje = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_extraccion},
                    {"type": "image_url", "image_url": {"url": image_data_uri}}
                ]
            )
            res = await asyncio.to_thread(self._llm.invoke, [mensaje])
            texto_respuesta = res.content
            if isinstance(texto_respuesta, list):
                texto_respuesta = "".join(
                    b if isinstance(b, str) else b.get("text", "")
                    for b in texto_respuesta
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
        """Genera la respuesta del asistente. Soporta entrada multimodal opcional."""
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

        respuesta_llm = await asyncio.to_thread(self._llm.invoke, [mensaje_llm])
        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = [b if isinstance(b, str) else b.get("text", "") for b in contenido]
            return "".join(partes)
        return str(contenido)