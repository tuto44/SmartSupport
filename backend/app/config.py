import os
from dotenv import load_dotenv

load_dotenv()


# =========================
# GOOGLE / GEMINI
# =========================

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

CHAT_MODEL = "gemini-3.5-flash-lite"
EMBEDDING_MODEL = "gemini-embedding-001"


# =========================
# QDRANT
# =========================

QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = "documentacion_ti"

TOP_K_RESULTS = 5
MIN_SIMILARITY_SCORE = 0.60


# =========================
# DOCUMENTOS
# =========================

DOCUMENTS_FOLDER = "./documentos"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


# =========================
# MYSQL
# =========================

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "smartsupport")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")