from langchain_google_genai import (GoogleGenerativeAIEmbeddings,ChatGoogleGenerativeAI)
from app.database.qdrant_manager import QdrantManager
from app.services.conversation_service import ConversationService
from app.prompts.system_prompt import construir_prompt
from app.config import (CHAT_MODEL,EMBEDDING_MODEL,MIN_SIMILARITY_SCORE,TOP_K_RESULTS)


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

        embedding = self.embedding_model.embed_query(
            pregunta
        )

        print(
            f"Embedding generado ({len(embedding)} dimensiones)."
        )

        return embedding

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

        print(
            f"Consulta utilizada para RAG:\n{consulta_rag}"
        )

        embedding = self.generar_embedding(
            consulta_rag
        )

        resultados = self.qdrant.buscar_similares(
            embedding=embedding,
            limite=limite
        )

        if not resultados:

            print("No se encontraron resultados.")

            return None

        print(
            f"Se encontraron {len(resultados)} resultados."
        )

        contexto = []

        for resultado in resultados:

            if resultado.score < MIN_SIMILARITY_SCORE:
                continue

            print(
                f"Score: {resultado.score:.4f}"
            )

            contenido = resultado.payload.get(
                "page_content"
            )

            if contenido:
                contexto.append(contenido)

        if not contexto:

            print(
                "Ningún resultado superó el umbral de similitud."
            )

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
        pregunta: str
    ) -> str:

        print("=" * 60)
        print("NUEVA CONSULTA")
        print("=" * 60)

        print(
            f"Usuario: {user_name}"
        )

        print(
            f"Conversation ID: {conversation_id}"
        )

        print(
            f"Pregunta: {pregunta}"
        )

        # -----------------------------------------------------
        # 1. OBTENER HISTORIAL
        # -----------------------------------------------------

        historial = self.conversation.obtener_historial(
            conversation_id=conversation_id,
            limite=8
        )

        print(
            f"Historial recuperado: {len(historial)} mensajes"
        )

        # -----------------------------------------------------
        # 2. BUSCAR INFORMACIÓN EN QDRANT
        # -----------------------------------------------------

        contexto = self.recuperar_contexto(
            pregunta=pregunta,
            historial=historial
        )

        # -----------------------------------------------------
        # 3. SI NO HAY INFORMACIÓN
        # -----------------------------------------------------

        if contexto is None:

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
                mensaje=pregunta
            )

            self.conversation.agregar_mensaje(
                conversation_id=conversation_id,
                user_id=user_id,
                user_name=user_name,
                rol="assistant",
                mensaje=respuesta
            )

            return respuesta

        # -----------------------------------------------------
        # 4. CONSTRUIR PROMPT
        # -----------------------------------------------------

        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial
        )

        # -----------------------------------------------------
        # 5. GENERAR RESPUESTA
        # -----------------------------------------------------

        respuesta_llm = self.llm.invoke(
            prompt
        )

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

        print(
            "Respuesta generada correctamente."
        )
        
        print(
        f"Tipo de respuesta Gemini: {type(contenido).__name__}"
        )

        # -----------------------------------------------------
        # 6. GUARDAR MENSAJE DEL USUARIO
        # -----------------------------------------------------

        self.conversation.agregar_mensaje(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            rol="user",
            mensaje=pregunta
        )

        # -----------------------------------------------------
        # 7. GUARDAR RESPUESTA DEL ASISTENTE
        # -----------------------------------------------------

        self.conversation.agregar_mensaje(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            rol="assistant",
            mensaje=respuesta
        )

        print(
            "Conversación guardada en MySQL."
        )

        return respuesta

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

        # Solo utilizamos los últimos 4 mensajes
        # para no enviar demasiado contenido al embedding.

        ultimos_mensajes = historial[-4:]

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
            "Contexto de la conversación:\n"
            + "\n".join(historial_texto)
            + f"\n\nPregunta actual:\n{pregunta}"
        )