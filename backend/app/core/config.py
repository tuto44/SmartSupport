import os
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Única fuente de verdad para la configuración del sistema.
    Centraliza credenciales, endpoints y validaciones estrictas en arranque.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Google / Gemini / LLM
    GOOGLE_API_KEY: str = Field(
        default="",
        description="API Key para servicios de Google Gemini y Embeddings"
    )
    CHAT_MODEL: str = Field(
        default="gemini-3.5-flash-lite",
        description="Identificador del modelo generativo multimodal"
    )
    EMBEDDING_MODEL: str = Field(
        default="gemini-embedding-001",
        description="Identificador del modelo para generación de embeddings"
    )

    # Qdrant Vector Database
    QDRANT_URL: str = Field(
        default="http://localhost:6333",
        description="URL del servicio de persistencia vectorial Qdrant"
    )
    QDRANT_API_KEY: Optional[str] = Field(
        default=None,
        description="API Key opcional para Qdrant Cloud o autenticación gRPC"
    )
    COLLECTION_NAME: str = Field(
        default="documentacion_ti",
        description="Nombre de la colección de vectores técnicos"
    )
    TOP_K_RESULTS: int = Field(
        default=5,
        description="Número máximo de fragmentos a recuperar en similitud"
    )
    MIN_SIMILARITY_SCORE: float = Field(
        default=0.60,
        description="Umbral mínimo de similitud coseno (calibrado a 0.45 para optimizar recall en búsquedas semánticas)"
    )

    # Documentación Técnica y Chunking
    DOCUMENTS_FOLDER: str = Field(
        default="../documentos",
        description="Directorio de manuales técnicos para indexación"
    )
    CHUNK_SIZE: int = Field(
        default=1100,
        description="Cantidad máxima de caracteres por chunk"
    )
    CHUNK_OVERLAP: int = Field(
        default=200,
        description="Solapamiento de caracteres entre chunks consecutivos"
    )

    # Sesión e Inactividad
    CONVERSATION_TIMEOUT_MINUTES: int = Field(
        default=15,
        description="Minutos de inactividad antes de finalizar y limpiar una conversación"
    )

    # Contacto Oficial de Soporte Local TI HWI
    TI_HWI_EMAIL: str = Field(
        default="administrador.ti@hacebwhirlpool.com",
        description="Correo oficial del Encargado de TI de HWI para escalamientos"
    )

    # MySQL / SQLAlchemy
    MYSQL_HOST: str = Field(
        default="localhost",
        description="Host del servidor MySQL"
    )
    MYSQL_PORT: int = Field(
        default=3306,
        description="Puerto de conexión a MySQL"
    )
    MYSQL_DATABASE: str = Field(
        default="smartsupport",
        description="Nombre de la base de datos relacional"
    )
    MYSQL_USER: str = Field(
        default="root",
        description="Usuario de conexión a MySQL"
    )
    MYSQL_PASSWORD: str = Field(
        default="",
        description="Contraseña de MySQL requerida desde variables de entorno"
    )

    # Google Chat / Integración OAuth2
    CHAT_ACTION_URL: str = Field(
        default="https://barrier-stammer-shush.ngrok-free.dev/api/google-chat",
        description="URL pública de webhook para callbacks interactivos"
    )
    SERVICE_ACCOUNT_FILE: str = Field(
        default=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "smartsupport-512916-06c4920912ab.json")
        ),
        description="Ruta absoluta al archivo de credenciales service_account.json"
    )
    GOOGLE_CHAT_SCOPES: list[str] = Field(
        default=["https://www.googleapis.com/auth/chat.bot"],
        description="Scopes OAuth2 autorizados para el bot de Google Chat"
    )

    @field_validator("GOOGLE_API_KEY")
    @classmethod
    def validar_google_api_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "La variable de entorno 'GOOGLE_API_KEY' es obligatoria para la operación del Asistente y LLM."
            )
        return v.strip()

    @property
    def database_url(self) -> str:
        """Construye la URL tipada de conexión para el dialecto mysqlconnector de SQLAlchemy."""
        return (
            f"mysql+mysqlconnector://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )


settings = Settings()