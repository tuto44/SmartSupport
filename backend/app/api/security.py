from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.config import config

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verificar_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != config.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso no autorizado: API Key interna inválida o ausente."
        )
    return api_key