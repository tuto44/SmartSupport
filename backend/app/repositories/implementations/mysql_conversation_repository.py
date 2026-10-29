import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from app.domain.models import ConversationDomain, ConversationState
from app.repositories.interfaces.conversation_repository import IConversationRepository
from app.repositories.implementations.models_orm import ConversationModel, ChatHistoryModel

logger = logging.getLogger(__name__)


class MySQLConversationRepository(IConversationRepository):
    """
    Implementación de IConversationRepository utilizando SQLAlchemy 2.0 ORM.

    El commit/rollback es responsabilidad exclusiva del Unit of Work en get_db().
    Este repositorio sólo opera con add(), execute() y flush() cuando se necesita
    leer un ID autogenerado inmediatamente. No usa begin_nested().
    """

    def __init__(self, session: Session):
        self._session = session

    # ------------------------------------------------------------------ #
    #  Mapeo ORM → Dominio                                                 #
    # ------------------------------------------------------------------ #

    def _to_domain(self, model: ConversationModel) -> ConversationDomain:
        return ConversationDomain(
            id=model.id,
            user_id=model.user_id,
            user_name=model.user_name,
            title=model.title,
            root_issue=model.root_issue,
            last_context=model.last_context,
            created_at=model.created_at,
            updated_at=model.updated_at
        )

    # ------------------------------------------------------------------ #
    #  Operaciones de Conversación                                         #
    # ------------------------------------------------------------------ #

    def crear_o_actualizar_conversacion(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        title: str = "Nueva conversación"
    ) -> ConversationDomain:
        """Crea o actualiza la cabecera de conversación. Sin begin_nested: el commit lo gestiona get_db()."""
        stmt = select(ConversationModel).where(ConversationModel.id == conversation_id)
        conv = self._session.scalars(stmt).first()

        if conv:
            conv.updated_at = datetime.utcnow()
            if user_name:
                conv.user_name = user_name
        else:
            conv = ConversationModel(
                id=conversation_id,
                user_id=user_id,
                user_name=user_name,
                title=title,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self._session.add(conv)
            self._session.flush()  # Necesario para que el ORM resuelva la PK antes de retornar

        return self._to_domain(conv)

    def obtener_conversacion(self, conversation_id: str) -> Optional[ConversationDomain]:
        stmt = select(ConversationModel).where(ConversationModel.id == conversation_id)
        conv = self._session.scalars(stmt).first()
        return self._to_domain(conv) if conv else None

    def obtener_estado_conversacion(self, conversation_id: str) -> ConversationState:
        stmt = select(ConversationModel.root_issue, ConversationModel.last_context).where(
            ConversationModel.id == conversation_id
        )
        row = self._session.execute(stmt).first()
        if not row:
            return ConversationState(root_issue=None, last_context=None)
        return ConversationState(root_issue=row[0], last_context=row[1])

    def actualizar_estado_conversacion(
        self,
        conversation_id: str,
        root_issue: Optional[str] = None,
        last_context: Optional[str] = None
    ) -> None:
        """Actualiza root_issue y/o last_context mediante ORM UPDATE. Sin begin_nested."""
        values_to_update: dict = {}
        if root_issue is not None:
            values_to_update["root_issue"] = root_issue
        if last_context is not None:
            values_to_update["last_context"] = last_context

        if not values_to_update:
            return

        values_to_update["updated_at"] = datetime.utcnow()

        stmt = (
            update(ConversationModel)
            .where(ConversationModel.id == conversation_id)
            .values(**values_to_update)
        )
        result = self._session.execute(stmt)
        logger.info(
            "[REPOSITORIO] Estado actualizado para '%s' (filas afectadas: %s)",
            conversation_id, result.rowcount
        )

    def obtener_historial(
        self,
        conversation_id: str,
        limite: int = 8
    ) -> List[dict]:
        stmt = (
            select(ChatHistoryModel.role, ChatHistoryModel.content)
            .where(ChatHistoryModel.conversation_id == conversation_id)
            .order_by(ChatHistoryModel.id.desc())
            .limit(limite)
        )
        rows = self._session.execute(stmt).all()
        mensajes = [{"role": r[0], "content": r[1]} for r in rows]
        mensajes.reverse()
        return mensajes

    def agregar_mensaje(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        rol: str,
        mensaje: str
    ) -> None:
        """
        Agrega un mensaje al historial y garantiza que la conversación padre exista.
        Sin begin_nested: el commit lo gestiona el Unit of Work en get_db().
        """
        stmt_conv = select(ConversationModel).where(ConversationModel.id == conversation_id)
        conv = self._session.scalars(stmt_conv).first()

        title = (
            mensaje[:30] + "..."
            if rol == "user" and mensaje
            else "Nueva conversación"
        )

        if conv:
            conv.updated_at = datetime.utcnow()
            if user_name:
                conv.user_name = user_name
        else:
            conv = ConversationModel(
                id=conversation_id,
                user_id=user_id,
                user_name=user_name,
                title=title,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            self._session.add(conv)
            self._session.flush()  # Resuelve FK antes de insertar el mensaje hijo

        msg = ChatHistoryModel(
            conversation_id=conversation_id,
            user_name=user_name,
            role=rol,
            content=mensaje,
            created_at=datetime.utcnow()
        )
        self._session.add(msg)

    def obtener_conversaciones(self, user_name: str) -> List[ConversationDomain]:
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.user_name == user_name)
            .order_by(ConversationModel.updated_at.desc())
        )
        results = self._session.scalars(stmt).all()
        return [self._to_domain(c) for c in results]

    def eliminar_conversacion(self, conversation_id: str) -> None:
        """
        Elimina el historial de chat y la conversación padre en cascada.
        La FK con ondelete=CASCADE en el ORM es suficiente, pero hacemos
        el DELETE explícito del hijo primero para mayor control.
        """
        stmt_chat = delete(ChatHistoryModel).where(
            ChatHistoryModel.conversation_id == conversation_id
        )
        self._session.execute(stmt_chat)

        stmt_conv = delete(ConversationModel).where(
            ConversationModel.id == conversation_id
        )
        self._session.execute(stmt_conv)
        logger.info(
            "[REPOSITORIO] Conversación '%s' eliminada con su historial asociado.",
            conversation_id
        )
