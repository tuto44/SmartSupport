from langchain_core.messages import HumanMessage
from langchain_google_genai import (ChatGoogleGenerativeAI,GoogleGenerativeAIEmbeddings,)
from app.config import (CHAT_MODEL,EMBEDDING_MODEL,MIN_SIMILARITY_SCORE,TOP_K_RESULTS,)
from app.database.qdrant_manager import QdrantManager
from app.prompts.system_prompt import construir_prompt
from app.services.conversation_service import ConversationService


class RagService:

    def __init__(self):
        self.qdrant = QdrantManager()
        self.conversation = ConversationService()
        self.embedding_model = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL
        )
        self.llm = ChatGoogleGenerativeAI(
            model=CHAT_MODEL,
            temperature=0.2
        )

    # ---------------------------------------------------------
    # EMBEDDING
    # ---------------------------------------------------------

    def generar_embedding(self, pregunta: str) -> list[float]:
        print("Generando embedding de la pregunta...")
        embedding = self.embedding_model.embed_query(pregunta)
        print(f"Embedding generado ({len(embedding)} dimensiones).")
        return embedding

    # ---------------------------------------------------------
    # EXTRACCIÓN VISUAL PREVIA PARA RAG
    # ---------------------------------------------------------

    def extraer_descripcion_imagen(self, image_base64: str) -> str:
        """Extrae el software y error técnico visible en la imagen para alimentar la búsqueda en Qdrant."""
        try:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            prompt_extraccion = (
                "Actúa como un analizador técnico de TI. Observa esta imagen y responde en 1 sola línea breve: "
                "el nombre del sistema o software (ej. VPN GlobalProtect, Citrix, Wpass, ServiceNow) "
                "y el código o mensaje de error textual que aparece. "
                "Responde únicamente palabras clave técnicas concisas."
            )
            mensaje = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_extraccion},
                    {"type": "image_url", "image_url": {"url": image_data_uri}}
                ]
            )
            res = self.llm.invoke([mensaje])
            texto = res.content
            if isinstance(texto, list):
                texto = "".join(
                    b if isinstance(b, str) else b.get("text", "")
                    for b in texto
                )
            descripcion = str(texto).strip()
            print(f"Información técnica extraída de la imagen: {descripcion}")
            return descripcion
        except Exception as e:
            print(f"Aviso: No se pudo extraer descripción previa de la imagen: {e}")
            return ""

    # ---------------------------------------------------------
    # CONSTRUIR CONSULTA PARA RAG
    # ---------------------------------------------------------

    def construir_consulta_rag(
        self,
        pregunta: str,
        historial: list
    ) -> str:
        if not historial:
            return pregunta

        # Si la consulta actual ya tiene suficiente detalle, la usamos directamente
        # para evitar diluir la similitud vectorial con saludos del historial
        palabras = pregunta.strip().split()
        if len(palabras) >= 5:
            return pregunta

        ultimos_mensajes = historial[-2:]
        historial_texto = []

        for mensaje in ultimos_mensajes:
            rol = (
                "Usuario"
                if mensaje["role"] == "user"
                else "Asistente"
            )
            historial_texto.append(
                f"{rol}: {mensaje['content']}"
            )

        return (
            "Contexto previo:\n"
            + "\n".join(historial_texto)
            + f"\nPregunta: {pregunta}"
        )

    # ---------------------------------------------------------
    # RECUPERAR CONTEXTO
    # ---------------------------------------------------------

    def recuperar_contexto(
        self,
        pregunta: str,
        historial: list,
        limite: int = TOP_K_RESULTS
    ) -> str | None:
        consulta_rag = self.construir_consulta_rag(
            pregunta=pregunta,
            historial=historial
        )

        print(f"Consulta utilizada para RAG:\n{consulta_rag}")

        embedding = self.generar_embedding(consulta_rag)

        resultados = self.qdrant.buscar_similares(
            embedding=embedding,
            limite=limite
        )

        if not resultados:
            print("No se encontraron resultados en Qdrant.")
            return None

        print(f"Se encontraron {len(resultados)} resultados.")

        contexto = []
        for resultado in resultados:
            if resultado.score < MIN_SIMILARITY_SCORE:
                continue

            print(f"Score: {resultado.score:.4f}")
            contenido = resultado.payload.get("page_content")
            if contenido:
                contexto.append(contenido)

        if not contexto:
            print("Ningún resultado superó el umbral de similitud.")
            return None

        return "\n\n".join(contexto)

    # ---------------------------------------------------------
    # RESPONDER
    # ---------------------------------------------------------

    def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: str | None = None
    ) -> str:
        print("=" * 60)
        print("NUEVA CONSULTA")
        print("=" * 60)
        print(f"Usuario: {user_name}")
        print(f"Conversation ID: {conversation_id}")
        print(f"Pregunta: {pregunta}")
        print(f"Imagen adjunta: {'Sí' if image_base64 else 'No'}")

        # 1. Análisis visual previo para enriquecer la búsqueda semántica
        descripcion_imagen = ""
        if image_base64:
            print("Analizando imagen adjunta para extraer términos de búsqueda...")
            descripcion_imagen = self.extraer_descripcion_imagen(image_base64)

        consulta_busqueda = (
            f"{pregunta} {descripcion_imagen}".strip()
            if descripcion_imagen
            else pregunta
        )

        # Formato de mensaje a almacenar en base de datos para no perder contexto visual
        if image_base64:
            if descripcion_imagen:
                mensaje_usuario_bd = f"[Imagen adjunta: {descripcion_imagen}] {pregunta}".strip()
            else:
                mensaje_usuario_bd = f"[Imagen adjunta] {pregunta}".strip()
        else:
            mensaje_usuario_bd = pregunta

        # 2. Obtener historial
        historial = self.conversation.obtener_historial(
            conversation_id=conversation_id,
            limite=8
        )
        print(f"Historial recuperado: {len(historial)} mensajes")

        # 3. Buscar información en Qdrant usando la consulta enriquecida
        contexto = self.recuperar_contexto(
            pregunta=consulta_busqueda,
            historial=historial
        )

        # 4. Validación de suficiencia de contexto
        respuestas_seguimiento = {
            "si", "sí", "no", "ya", "ya lo hice", "listo", "no funcionó",
            "no me deja", "ok", "vale", "ya está", "ya termine", "ya terminé",
            "funciono", "funcionó"
        }
        es_respuesta_corta = pregunta.strip().lower() in respuestas_seguimiento

        if contexto is None:
            if es_respuesta_corta and historial:
                print("Respuesta de seguimiento en diálogo activo. Continuando diagnóstico.")
                contexto = "Continuación del diagnóstico según el historial previo."
            elif image_base64:
                print("No se encontró documentación exacta, pero hay imagen adjunta. Pasando imagen al modelo.")
                contexto = (
                    "No se encontró un artículo específico para este caso exacto en la base de conocimientos. "
                    "Analiza la imagen adjunta para diagnosticar el problema del usuario."
                )
            else:
                respuesta = (
                    "No encontré información relacionada con tu "
                    "consulta en la documentación disponible. "
                    "Te recomiendo contactar al área de TI."
                )
                self.conversation.agregar_mensaje(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_name=user_name,
                    rol="user",
                    mensaje=mensaje_usuario_bd
                )
                self.conversation.agregar_mensaje(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_name=user_name,
                    rol="assistant",
                    mensaje=respuesta
                )
                return respuesta

        # 5. Construir prompt y mensaje multimodal
        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial
        )

        if image_base64:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            contenido_mensaje = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_uri}
                }
            ]
            mensaje_llm = HumanMessage(content=contenido_mensaje)
        else:
            mensaje_llm = HumanMessage(content=prompt)

        # 6. Generar respuesta con el LLM
        respuesta_llm = self.llm.invoke([mensaje_llm])
        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = []
            for bloque in contenido:
                if isinstance(bloque, str):
                    partes.append(bloque)
                elif isinstance(bloque, dict):
                    texto = bloque.get("text")
                    if texto:
                        partes.append(texto)
            respuesta = "".join(partes)
        else:
            respuesta = str(contenido)

        print("Respuesta generada correctamente.")
        print(f"Tipo de respuesta Gemini: {type(contenido).__name__}")

        # 6. Guardar mensaje del usuario en MySQL
        self.conversation.agregar_mensaje(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            rol="user",
            mensaje=mensaje_usuario_bd
        )

        # 7. Guardar respuesta del asistente en MySQL
        self.conversation.agregar_mensaje(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            rol="assistant",
            mensaje=respuesta
        )

        print("Conversación guardada en MySQL.")
        return respuesta