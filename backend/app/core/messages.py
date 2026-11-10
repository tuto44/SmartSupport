"""Mensajes de usuario compartidos entre capas.

Este módulo no debe depender de infraestructura (FastAPI, SQLAlchemy, Google),
de modo que pueda utilizarse tanto desde servicios como desde la capa API.
"""

# Aviso proactivo cuando el procesamiento excede el umbral de espera habitual.
MENSAJE_PROCESANDO = (
    "⏳ La petición está tardando un poco más de lo normal, por favor espera..."
)

# Último recurso: sólo se envía cuando se agotan todos los reintentos.
MENSAJE_ERROR_RESCATE = (
    "Hubo un error al procesar tu solicitud. Por favor, intenta de nuevo."
)
