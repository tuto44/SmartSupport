import logging

# Rutas de sondeo que no deben ensuciar el access log de Uvicorn.
# Actualmente el CLI de OpenCode consulta /health cada 30 segundos.
_RUTAS_SILENCIADAS = {"/health", "/healthz", "/ready", "/readyz"}


class _FiltroSondeosAccessLog(logging.Filter):
    """Descarta del access log las peticiones de health checks externos."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            ruta = args[2]
            if isinstance(ruta, str):
                ruta_limpia = ruta.split("?", 1)[0].rstrip("/") or "/"
                if ruta_limpia in _RUTAS_SILENCIADAS:
                    return False
        return True


def configurar_logging() -> None:
    """
    Aplica filtros de logging de la aplicación.

    No altera el comportamiento HTTP: las rutas siguen respondiendo igual
    (por ejemplo, /health continúa devolviendo 404). Solo evita que los
    sondeos periódicos aparezcan en la terminal del contenedor.
    """
    access_logger = logging.getLogger("uvicorn.access")
    ya_aplicado = any(
        isinstance(filtro, _FiltroSondeosAccessLog)
        for filtro in access_logger.filters
    )
    if not ya_aplicado:
        access_logger.addFilter(_FiltroSondeosAccessLog())
