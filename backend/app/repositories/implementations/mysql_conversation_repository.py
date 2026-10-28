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
    """Implementación de IConversationRepository utilizando SQLAlchemy 2.0 ORM."""

    def __init__(self, session: Session):
        self._session = session

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

    def crear_o_actualizar_conversacion(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        title: str = "Nueva conversación"
    ) -> ConversationDomain:
        with self._session.begin_nested():
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
            self._session.flush()
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
        values_to_update = {}
        if root_issue is not None:
            values_to_update["root_issue"] = root_issue
        if last_context is not None:
            values_to_update["last_context"] = last_context

        if not values_to_update:
            return

        values_to_update["updated_at"] = datetime.utcnow()

        with self._session.begin_nested():
            stmt = (
                update(ConversationModel)
                .where(ConversationModel.id == conversation_id)
                .values(**values_to_update)
            )
            result = self._session.execute(stmt)
            logger.info("[SQLAlchemy] Estado actualizado para %s (filas: %s)", conversation_id, result.rowcount)

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
        with self._session.begin_nested():
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

            msg = ChatHistoryModel(
                conversation_id=conversation_id,
                user_name=user_name,
                role=rol,
                content=mensaje,
                created_at=datetime.utcnow()
            )
            self._session.add(msg)
            self._session.flush()

    def obtener_conversaciones(self, user_name: str) -> List[ConversationDomain]:
        stmt = (
            select(ConversationModel)
            .where(ConversationModel.user_name == user_name)
            .order_by(ConversationModel.updated_at.desc())
        )
        results = self._session.scalars(stmt).all()
        return [self._to_domain(c) for c in results]

    def eliminar_conversacion(self, conversation_id: str) -> None:
        with self._session.begin_nested():
            stmt_chat = delete(ChatHistoryModel).where(ChatHistoryModel.conversation_id == conversation_id)
            self._session.execute(stmt_chat)

            stmt_conv = delete(ConversationModel).where(ConversationModel.id == conversation_id)
            self._session.execute(stmt_conv)
            logger.info("[SQLAlchemy] Conversación %s eliminada por reinicio de contexto.", conversation_id)
