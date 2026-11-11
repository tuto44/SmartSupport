import asyncio
import logging
import time
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest
from app.core.config import settings

logger = logging.getLogger(__name__)

_cached_credentials = None
_token_cache: Optional[str] = None
_token_expiry: float = 0.0


def _crear_session_resiliente() -> requests.Session:
    """
    Crea una sesión de requests configurada con reintentos para mitigar
    microcortes de red o caídas abruptas de socket TLS (SSLEOFError).
    """
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


async def obtener_token_google_chat() -> Optional[str]:
    """
    Obtiene y almacena en caché el token OAuth2 de la Service Account de Google Chat.
    Incluye lógica de reintentos para resiliencia ante errores de conexión SSL.
    """
    global _cached_credentials, _token_cache, _token_expiry

    ahora = time.time()
    # Retornar token en caché si aún es válido (margen de seguridad de 60s)
    if _token_cache and ahora < (_token_expiry - 60):
        return _token_cache

    if not settings.SERVICE_ACCOUNT_FILE:
        logger.warning("[SECURITY] GOOGLE_SERVICE_ACCOUNT_FILE no configurado.")
        return None

    try:
        if _cached_credentials is None:
            _cached_credentials = service_account.Credentials.from_service_account_file(
                settings.SERVICE_ACCOUNT_FILE,
                scopes=["https://www.googleapis.com/auth/chat.bot"]
            )

        session = _crear_session_resiliente()
        auth_request = GoogleAuthRequest(session=session)

        def _refresh():
            _cached_credentials.refresh(auth_request)
            return _cached_credentials.token, _cached_credentials.expiry.timestamp()

        # Reintentar hasta 3 veces si hay un corte de conexión o fallo SSL transitorio
        max_intentos = 3
        for intento in range(1, max_intentos + 1):
            try:
                token, expiry = await asyncio.to_thread(_refresh)
                _token_cache = token
                _token_expiry = expiry
                logger.info("[SECURITY] Token de Google Chat obtenido con éxito.")
                return _token_cache
            except Exception as e:
                logger.warning(
                    "[SECURITY ADVERTENCIA] Intento %d/%d falló al renovar token: %s",
                    intento, max_intentos, e
                )
                if intento == max_intentos:
                    raise e
                await asyncio.sleep(1.0 * intento)

    except Exception as error:
        logger.error("[SECURITY ERROR] Error al generar token de Google Chat: %s", error, exc_info=True)
        return None