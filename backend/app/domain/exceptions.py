class DomainException(Exception):
    """Excepción base del dominio."""
    pass


class ConversationNotFoundException(DomainException):
    """Lanzada cuando no se encuentra una conversación requerida."""
    pass


class VectorStoreError(DomainException):
    """Lanzada cuando ocurre una falla en el repositorio vectorial."""
    pass


class ExternalServiceError(DomainException):
    """Lanzada ante fallas de integración con servicios externos (LLM, Google API)."""
    pass
