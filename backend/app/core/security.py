import asyncio
import logging
import os
from fastapi import Request, HTTPException
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account, id_token
from app.core.config import settings

logger = logging.getLogger(__name__)

_cached_credentials: service_account.Credentials | None = None
_credentials_lock = asyncio.Lock()


async def obtener_token_google_chat() -> str | None:
    global _cached_credentials
    service_account_path = settings.SERVICE_ACCOUNT_FILE
    if not os.path.exists(service_account_path):
        candidatos = [
            "/app/smartsupport-512916-06c4920912ab.json",
            os.path.abspath(os.path.join(os.getcwd(), "smartsupport-512916-06c4920912ab.json")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "smartsupport-512916-06c4920912ab.json")),
        ]
        encontrado = None
        for c in candidatos:
            if os.path.exists(c):
                encontrado = c
                break
        if encontrado:
            service_account_path = encontrado
        else:
            return None

    async with _credentials_lock:
        try:
            def _refresh():
                nonlocal service_account_path
                global _cached_credentials
                if _cached_credentials is None:
                    _cached_credentials = service_account.Credentials.from_service_account_file(
                        service_account_path, scopes=settings.GOOGLE_CHAT_SCOPES
                    )
                if not _cached_credentials.valid:
                    _cached_credentials.refresh(GoogleAuthRequest())
                return _cached_credentials.token
            return await asyncio.to_thread(_refresh)
        except Exception as e:
            logger.error("[SECURITY] Error al generar token bot: %s", e)
            return None


def verify_chat_signature(request: Request) -> dict:
    """
    Middleware/Dependencia de FastAPI. Valida que el webhook entrante provenga 
    firmado con certeza desde Google Workspace hacia nuestro ID de proyecto.
    """
    project_number = settings.GOOGLE_CHAT_PROJECT_NUMBER
    if not project_number:
        logger.warning("[SECURITY] GOOGLE_CHAT_PROJECT_NUMBER no configurado. Se omite validación (Solo para Dev).")
        return {}

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization ausente o inválido")

    token = auth_header.split(" ")[1]
    try:
        req = GoogleAuthRequest()
        payload = id_token.verify_oauth2_token(token, req, audience=project_number)
        if payload.get("iss") not in ["chat@system.gserviceaccount.com"]:
            raise ValueError("El emisor (issuer) del token no pertenece a Google Chat.")
        return payload
    except Exception as e:
        logger.error("[SECURITY] Verificación JWT de Google Chat fallida: %s", e)
        raise HTTPException(status_code=401, detail="Firma de Google Chat inválida")