from app.services.rag_service import RagService

rag = RagService()

respuesta = rag.responder(
    usuario="Ricardo",
    pregunta="¿Cómo ingreso a Citrix?"
)

print(respuesta)