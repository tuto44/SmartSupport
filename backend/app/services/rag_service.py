from langchain_core.messages import HumanMessage
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from app.config import (
    CHAT_MODEL,
    EMBEDDING_MODEL,
    MIN_SIMILARITY_SCORE,
    TOP_K_RESULTS,
)
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

    def generar_embedding(self, pregunta: str) -> list[float]:
        return self.embedding_model.embed_query(pregunta)

    def extraer_descripcion_imagen(self, image_base64: str) -> str:
        try:
            image_data_uri = (
                image_base64
                if image_base64.startswith("data:image")
                else f"data:image/jpeg;base64,{image_base64}"
            )
            prompt_extraccion = (
                "Actúa como un analizador técnico de TI. Observa esta imagen y responde en 1 sola línea breve: "
                "el nombre del software o sistema involucrado y el mensaje o código de error textual exacto. "
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
                texto = "".join(b if isinstance(b, str) else b.get("text", "") for b in texto)
            descripcion = str(texto).strip()
            print(f"[RAG] Términos técnicos extraídos de imagen: {descripcion}")
            return descripcion
        except Exception as e:
            print(f"[RAG AVISO] No se pudo analizar la imagen previamente: {e}")
            return ""

    def recuperar_contexto(
        self,
        pregunta: str,
        limite: int = TOP_K_RESULTS
    ) -> str | None:
        print(f"[RAG] Búsqueda vectorial para: '{pregunta}'")
        embedding = self.generar_embedding(pregunta)
        resultados = self.qdrant.buscar_similares(embedding=embedding, limite=limite)

        if not resultados:
            return None

        contexto = []
        for resultado in resultados:
            if resultado.score < MIN_SIMILARITY_SCORE:
                continue
            contenido = resultado.payload.get("page_content")
            if contenido:
                contexto.append(contenido)

        if not contexto:
            return None

        return "\n\n".join(contexto)

    def responder(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        pregunta: str,
        image_base64: str | None = None
    ) -> str:
        print("=" * 60)
        print("NUEVA CONSULTA ENTRADA")
        print("=" * 60)
        print(f"Usuario: {user_name} | ID: {conversation_id}")
        print(f"Pregunta: {pregunta}")

        # 1. Asegurar la existencia de la conversación en BD ANTES de cualquier UPDATE
        self.conversation.crear_conversacion(
            conversation_id=conversation_id,
            user_id=user_id,
            user_name=user_name,
            title=pregunta[:30] + ("..." if len(pregunta) > 30 else "")
        )

        # 2. Análisis de imagen si existe
        descripcion_imagen = ""
        if image_base64:
            descripcion_imagen = self.extraer_descripcion_imagen(image_base64)

        mensaje_usuario_bd = (
            f"[Imagen: {descripcion_imagen}] {pregunta}".strip()
            if (image_base64 and descripcion_imagen)
            else f"[Imagen adjunta] {pregunta}".strip() if image_base64 else pregunta
        )

        # 3. Historial y Estado guardado de la Conversación
        historial = self.conversation.obtener_historial(conversation_id=conversation_id, limite=8)
        estado_conv = self.conversation.obtener_estado_conversacion(conversation_id)
        root_issue = estado_conv.get("root_issue")
        last_context = estado_conv.get("last_context")

        # 4. Manejo de saludos iniciales
        SALUDOS = {
            "hola", "buenas", "buen dia", "buen día", "buenos dias", "buenos días",
            "buenas tardes", "buenas noches", "hey", "saludos", "hola!", "que tal", "qué tal", "iniciar"
        }
        pregunta_limpia = pregunta.strip().lower()
        pregunta_normalizada = "".join(c for c in pregunta_limpia if c.isalnum() or c.isspace()).strip()

        if pregunta_normalizada in SALUDOS and not historial:
            respuesta_saludo = (
                f"¡Hola, {user_name}! 👋\n\n"
                "Soy tu Asistente Técnico de TI Nivel 1. ¿En qué problema, sistema o requerimiento "
                "(VPN, WPass, Citrix, correo, accesos, impresoras) te puedo ayudar hoy?"
            )
            self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "user", pregunta)
            self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "assistant", respuesta_saludo)
            return respuesta_saludo

        # 5. Detectar respuestas cortas o confirmaciones
        respuestas_seguimiento = {
            "si", "sí", "no", "ya", "ya lo hice", "listo", "no funcionó",
            "no me deja", "ok", "vale", "ya está", "ya termine", "ya terminé",
            "funciono", "funcionó", "siguiente", "continuar", "sigue igual"
        }
        es_respuesta_corta = pregunta_limpia in respuestas_seguimiento or (len(pregunta.split()) <= 2 and bool(historial))

        # 6. Establecer Objetivo Raíz si es el primer incidente técnico
        if not root_issue and not es_respuesta_corta and len(pregunta.split()) >= 3:
            root_issue = f"{pregunta} {descripcion_imagen}".strip()
            self.conversation.actualizar_estado_conversacion(
                conversation_id=conversation_id,
                root_issue=root_issue
            )
            print(f"[RAG] Objetivo raíz establecido: {root_issue}")

        # 7. Detectar si el usuario resolvió un bloqueo secundario
        frases_recuperacion = {
            "ya tengo internet", "ya cargo", "ya cargó", "ya navega",
            "ya volvio el internet", "ya volvió el internet", "ya conecto el wifi",
            "ya tengo red", "ya dio ip", "ya conecto internet"
        }
        resolvio_bloqueo = any(frase in pregunta_limpia for frase in frases_recuperacion)

        # 8. Formular la consulta para Qdrant
        if resolvio_bloqueo and root_issue:
            print("[RAG] Detectada resolución de bloqueo. Retomando objetivo raíz...")
            consulta_busqueda = f"{root_issue} pasos solución"
        elif es_respuesta_corta:
            consulta_busqueda = None  # No buscar palabras como "Sí" o "Listo" en Qdrant
        elif descripcion_imagen:
            consulta_busqueda = f"{pregunta} {descripcion_imagen}".strip()
        else:
            consulta_busqueda = pregunta

        # 9. Recuperar Contexto Documental
        contexto = None
        if consulta_busqueda:
            contexto = self.recuperar_contexto(pregunta=consulta_busqueda)

        # 10. Decisión del contexto activo con red de seguridad
        if contexto:
            self.conversation.actualizar_estado_conversacion(
                conversation_id=conversation_id,
                last_context=contexto
            )
        elif last_context:
            print("[RAG] Reutilizando manual activo guardado en BD.")
            contexto = last_context
        elif es_respuesta_corta and historial:
            # RED DE SEGURIDAD: Si no había last_context pero hay historial, reconstruir desde la última pregunta
            print("[RAG SEGURIDAD] Respuesta corta sin last_context en BD. Reconstruyendo desde historial...")
            mensajes_usuario_previos = [m["content"] for m in historial if m["role"] == "user"]
            if mensajes_usuario_previos:
                consulta_recuperada = mensajes_usuario_previos[-1]
                contexto = self.recuperar_contexto(pregunta=consulta_recuperada)
                if contexto:
                    self.conversation.actualizar_estado_conversacion(
                        conversation_id=conversation_id,
                        last_context=contexto
                    )
        elif image_base64:
            contexto = (
                "No se encontró un manual específico en la base de conocimientos. "
                "Diagnostica el problema técnico analizando visualmente la imagen adjunta."
            )

        # Si tras todos los intentos no hay contexto
        if not contexto:
            respuesta = (
                "No encontré información relacionada con tu consulta en la documentación disponible. "
                "Te recomiendo contactar al área de TI."
            )
            self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "user", mensaje_usuario_bd)
            self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "assistant", respuesta)
            return respuesta

        # 11. Construir Prompt Multimodal
        prompt = construir_prompt(
            usuario=user_name,
            pregunta=pregunta,
            contexto=contexto,
            historial=historial,
            root_issue=root_issue
        )

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

        # 12. Invocar Modelo
        respuesta_llm = self.llm.invoke([mensaje_llm])
        contenido = respuesta_llm.content

        if isinstance(contenido, list):
            partes = [b if isinstance(b, str) else b.get("text", "") for b in contenido]
            respuesta = "".join(partes)
        else:
            respuesta = str(contenido)

        # 13. Persistir interacción en Base de Datos
        self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "user", mensaje_usuario_bd)
        self.conversation.agregar_mensaje(conversation_id, user_id, user_name, "assistant", respuesta)

        print("[RAG] Respuesta de seguimiento generada y guardada exitosamente.")
        return respuesta