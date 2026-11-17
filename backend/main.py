from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.v1.routes import router as v1_router
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialización controlada de esquemas de base de datos
    try:
        init_db()
        print("[DATABASE] Tablas declarativas verificadas/inicializadas correctamente.")
    except Exception as e:
        print(f"[DATABASE AVISO] Inicialización de tablas omitida o con error: {e}")
    yield


app = FastAPI(
    title="GABI - Guía y Asistencia Business Intelligent",
    version="2.0.0",
    description="Backend para GABI - Asistente Virtual Corporativo HWI",
    lifespan=lifespan
)

app.include_router(
    v1_router,
    prefix="/api",
    tags=["Chat"]
)
