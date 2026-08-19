from langchain_google_genai import (GoogleGenerativeAIEmbeddings,ChatGoogleGenerativeAI)
from app.database.qdrant_manager import QdrantManager
from app.services.conversation_service import ConversationService
from app.prompts.system_prompt import construir_prompt 
from app.config import CHAT_MODEL, EMBEDDING_MODEL, MIN_SIMILARITY_SCORE, TOP_K_RESULTS
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
        
    def generar_embedding(self, pregunta: str) -> list[float]:
        print("Generando embedding de la pregunta...")
        embedding = self.embedding_model.embed_query(pregunta)
        print(f"Embedding generado ({len(embedding)} dimensiones).")
        return embedding
    
    def recuperar_contexto(self,pregunta: str,historial: list,limite: int = TOP_K_RESULTS) -> str:
        consulta_rag = self.construir_consulta_rag(
            pregunta=pregunta,
            historial=historial)
        print(f"Consulta utilizada para RAG:\n{consulta_rag}")
        embedding = self.generar_embedding(consulta_rag)
        resultados = self.qdrant.buscar_similares(
            embedding=embedding,
            limite=limite)
        if not resultados:
            return None
        print(f"Se encontraron {len(resultados)} resultados.")
        contexto = []
        for resultado in resultados:
            if resultado.score < MIN_SIMILARITY_SCORE:
                continue
            print(f"Score: {resultado.score:.4f}")
            contexto.append(
                resultado.payload["page_content"])
        if not contexto:
            print("Ningún resultado superó el umbral de similitud.")
            return None
        return "\n\n".join(contexto)  
    

    def responder(self, usuario: str, pregunta: str) -> str:
        print(f"Pregunta: {pregunta}")
        historial = self.conversation.obtener_historial(usuario)
        contexto = self.recuperar_contexto(
            pregunta=pregunta,
            historial=historial)
        if contexto is None:
            respuesta = (
                "No encontré información relacionada con tu consulta en la "
                "documentación disponible. Te recomiendo contactar al área de TI.")
            self.conversation.agregar_mensaje(
                usuario,
                "user",
                pregunta)
            self.conversation.agregar_mensaje(
                usuario,
                "assistant",
                respuesta)
            return respuesta
        prompt = construir_prompt(
            usuario=usuario,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial)
        respuesta = self.llm.invoke(prompt)
        print("Respuesta generada correctamente.")
        self.conversation.agregar_mensaje(
            usuario,
            "user",
            pregunta)
        self.conversation.agregar_mensaje(
            usuario,
            "assistant",
            respuesta.text)
        return respuesta.text
    
    def construir_consulta_rag(self,pregunta: str,historial: list) -> str:
        if not historial:
            return pregunta
        ultimos_mensajes = historial[-4:]
        historial_texto = []
        for mensaje in ultimos_mensajes:
            rol = "Usuario" if mensaje["role"] == "user" else "Asistente"
            historial_texto.append(
                f"{rol}: {mensaje['content']}")
        return (
            "Contexto de la conversación:\n"
            + "\n".join(historial_texto)
            + f"\n\nPregunta actual:\n{pregunta}")