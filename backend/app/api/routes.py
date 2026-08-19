from fastapi import APIRouter

from app.models.chat_request import ChatRequest
from app.services.rag_service import RagService

router = APIRouter()

rag_service = RagService()


@router.post("/chat")
async def chat(request: ChatRequest):

    respuesta = rag_service.responder(
        usuario=request.user_name,
        pregunta=request.question
    )

    return {
        "status": "success",
        "answer": respuesta
    }