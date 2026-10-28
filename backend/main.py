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
    title="Asistente Inteligente TI",
    version="2.0.0",
    description="Backend para SmartSupport - Asistente de TI Nivel 1 con Clean Architecture",
    lifespan=lifespan
)

app.include_router(
    v1_router,
    prefix="/api",
    tags=["Chat"]
)
