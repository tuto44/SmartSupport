from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Asistente Inteligente TI")

app.include_router(
    router, prefix="/api", tags=["Chat"]
)