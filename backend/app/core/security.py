import asyncio
import os
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from app.core.config import settings

_cached_credentials: service_account.Credentials | None = None
_credentials_lock = asyncio.Lock()


async def obtener_token_google_chat() -> str | None:
    """
    Obtiene o refresca un Bearer Token usando service_account.json con caché en memoria.
    Protegido concurrentemente mediante asyncio.Lock para evitar condiciones de carrera.
    """
    global _cached_credentials

    service_account_path = settings.SERVICE_ACCOUNT_FILE
    if not os.path.exists(service_account_path):
        # Fallback para resolver la ruta tanto si se corre en Docker (/app/) como localmente
        candidatos = [
            os.path.abspath(os.path.join(os.getcwd(), "service_account.json")),
            "/app/service_account.json",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "service_account.json")),
        ]
        encontrado = None
        for c in candidatos:
            if os.path.exists(c):
                encontrado = c
                break
        if encontrado:
            service_account_path = encontrado
        else:
            print(f"[SECURITY] Advertencia: Archivo '{service_account_path}' no encontrado.")
            return None

    async with _credentials_lock:
        try:
            # Ejecutar operaciones síncronas de auth en un hilo separado
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

            token = await asyncio.to_thread(_refresh)
            return token
        except Exception as e:
            print(f"[SECURITY ERROR] Error al generar token de Google Chat: {e}")
            return None
