import os
from dotenv import load_dotenv

load_dotenv()


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
CHAT_MODEL = "gemini-3.5-flash-lite"
EMBEDDING_MODEL = "gemini-embedding-001"


QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = "documentacion_ti"



TOP_K_RESULTS = 5
MIN_SIMILARITY_SCORE = 0.60



DOCUMENTS_FOLDER = "./documentos"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100