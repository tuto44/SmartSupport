from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Generador de sesiones con commit al finalizar y rollback ante excepciones."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Inicializa esquemas y tablas declarativas controladas por SQLAlchemy."""
    # Importación explícita para registrar modelos en la metadata
    import app.repositories.implementations.models_orm  # noqa: F401
    Base.metadata.create_all(bind=engine)