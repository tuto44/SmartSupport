import logging
from typing import Any, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Extractores Recursivos de Resiliencia para Google Chat             #
# ------------------------------------------------------------------ #

def _extract_space_recursive(data: Any) -> str:
    """Busca recursivamente cualquier identificador que inicie con 'spaces/'."""
    if isinstance(data, dict):
        for key in ["name", "spaceName", "space"]:
            val = data.get(key)
            if isinstance(val, str) and val.startswith("spaces/"):
                return val.split("/threads/")[0].split("/messages/")[0]
        for val in data.values():
            found = _extract_space_recursive(val)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_space_recursive(item)
            if found:
                return found
    elif isinstance(data, str) and data.startswith("spaces/"):
        return data.split("/threads/")[0].split("/messages/")[0]
    return ""


def _extract_text_recursive(data: Any) -> str:
    """Busca recursivamente el texto del mensaje del usuario."""
    if isinstance(data, dict):
        # Priorizar argumentText (mensaje limpio sin @mención del bot)
        for key in ["argumentText", "text", "reply", "value"]:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for k, v in data.items():
            if k not in {"actionResponse", "cardsV2", "cards"}:
                found = _extract_text_recursive(v)
                if found:
                    return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_text_recursive(item)
            if found:
                return found
    return ""


def _extract_user_recursive(data: Any) -> str:
    """Busca recursivamente el nombre de visualización del usuario."""
    if isinstance(data, dict):
        if "displayName" in data and isinstance(data["displayName"], str) and data["displayName"].strip():
            return data["displayName"].strip()
        for k, v in data.items():
            found = _extract_user_recursive(v)
            if found and found != "Usuario Google Chat":
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_user_recursive(item)
            if found and found != "Usuario Google Chat":
                return found
    return "Usuario Google Chat"


def _extract_thread_recursive(data: Any) -> str:
    """Busca recursivamente el nombre del thread."""
    if isinstance(data, dict):
        thread_obj = data.get("thread")
        if isinstance(thread_obj, dict) and thread_obj.get("name"):
            return thread_obj["name"]
        thread_name = data.get("threadName")
        if isinstance(thread_name, str) and thread_name:
            return thread_name
        for val in data.values():
            found = _extract_thread_recursive(val)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_thread_recursive(item)
            if found:
                return found
    return ""


# ------------------------------------------------------------------ #
#  Modelos de Esquema Pydantic Tipados                                #
# ------------------------------------------------------------------ #

class BaseChatModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class UserSchema(BaseChatModel):
    name: Optional[str] = None
    displayName: Optional[str] = None
    type: Optional[str] = None


class SpaceSchema(BaseChatModel):
    name: Optional[str] = None
    type: Optional[str] = None
    displayName: Optional[str] = None
    singleUserBotDm: Optional[bool] = None


class ThreadSchema(BaseChatModel):
    name: Optional[str] = None


class AttachmentDataRef(BaseChatModel):
    resourceName: Optional[str] = None


class AttachmentSchema(BaseChatModel):
    name: Optional[str] = None
    contentType: Optional[str] = None
    attachmentDataRef: Optional[AttachmentDataRef] = None


class MessagePayloadSchema(BaseChatModel):
    name: Optional[str] = None
    text: Optional[str] = None
    argumentText: Optional[str] = None
    sender: Optional[UserSchema] = None
    thread: Optional[ThreadSchema] = None
    space: Optional[SpaceSchema] = None
    attachment: Optional[List[AttachmentSchema]] = None
    attachments: Optional[List[AttachmentSchema]] = None
    threadReply: Optional[bool] = None


class ActionParameter(BaseChatModel):
    key: str
    value: Optional[str] = None


class CommonEventObjectSchema(BaseChatModel):
    invokedFunction: Optional[str] = None
    parameters: Optional[Union[dict[str, Any], List[ActionParameter]]] = None


class ActionEventSchema(BaseChatModel):
    function: Optional[str] = None
    actionMethodName: Optional[str] = None
    parameters: Optional[Union[dict[str, Any], List[ActionParameter]]] = None


class NestedChatObject(BaseChatModel):
    user: Optional[UserSchema] = None
    space: Optional[SpaceSchema] = None
    messagePayload: Optional[MessagePayloadSchema] = None
    buttonClickedPayload: Optional[dict[str, Any]] = None
    actionEvent: Optional[ActionEventSchema] = None


class GoogleChatWebhookEvent(BaseChatModel):
    type: Optional[str] = None
    user: Optional[UserSchema] = None
    space: Optional[SpaceSchema] = None
    message: Optional[MessagePayloadSchema] = None
    thread: Optional[ThreadSchema] = None
    chat: Optional[NestedChatObject] = None
    buttonClickedPayload: Optional[dict[str, Any]] = None
    commonEventObject: Optional[CommonEventObjectSchema] = None
    action: Optional[ActionEventSchema] = None
    raw_payload: Optional[dict[str, Any]] = Field(default=None, alias="_raw_payload")

    @model_validator(mode="before")
    @classmethod
    def capturar_payload_completo(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Preservar el payload completo para fallbacks recursivos
            data["_raw_payload"] = dict(data)
        return data

    def get_user_display_name(self) -> str:
        candidates = [
            self.chat.user.displayName if self.chat and self.chat.user else None,
            self.chat.user.name if self.chat and self.chat.user else None,
            self.user.displayName if self.user else None,
            self.user.name if self.user else None,
            self.message.sender.displayName if self.message and self.message.sender else None,
            self.message.sender.name if self.message and self.message.sender else None,
            self.chat.messagePayload.sender.displayName if self.chat and self.chat.messagePayload and self.chat.messagePayload.sender else None,
        ]
        for name in candidates:
            if name:
                return name
        if self.raw_payload:
            return _extract_user_recursive(self.raw_payload)
        return "Usuario Google Chat"

    def get_user_id(self) -> str:
        candidates = [
            self.chat.user.name if self.chat and self.chat.user else None,
            self.user.name if self.user else None,
            self.message.sender.name if self.message and self.message.sender else None,
            self.chat.messagePayload.sender.name if self.chat and self.chat.messagePayload and self.chat.messagePayload.sender else None,
        ]
        for uid in candidates:
            if uid:
                return uid
        return self.get_user_display_name()

    def get_space(self) -> tuple[str, str]:
        """Retorna (space_name, space_type) buscando en modelos tipados y recursivamente."""
        candidates = [
            self.chat.space if self.chat else None,
            self.space,
            self.message.space if self.message else None,
            self.chat.messagePayload.space if self.chat and self.chat.messagePayload else None,
        ]
        for sp in candidates:
            if sp:
                if isinstance(sp, SpaceSchema) and sp.name:
                    return sp.name, sp.type or ""
                elif isinstance(sp, dict) and sp.get("name"):
                    return sp["name"], sp.get("type", "")
                elif isinstance(sp, str) and sp.startswith("spaces/"):
                    return sp, ""

        # Fallback en campos extra o thread
        thread = self.get_thread_name()
        if thread and thread.startswith("spaces/"):
            return thread.split("/threads/")[0], ""

        if self.message and self.message.name and self.message.name.startswith("spaces/"):
            return self.message.name.split("/messages/")[0], ""

        # Fallback recursivo sobre todo el JSON recibido
        if self.raw_payload:
            sp = _extract_space_recursive(self.raw_payload)
            if sp:
                return sp, ""

        return "", ""

    def get_thread_name(self) -> str:
        candidates = [
            self.message.thread.name if self.message and self.message.thread else None,
            self.thread.name if self.thread else None,
            self.chat.messagePayload.thread.name if self.chat and self.chat.messagePayload and self.chat.messagePayload.thread else None,
        ]
        for th in candidates:
            if th:
                return th

        if self.raw_payload:
            return _extract_thread_recursive(self.raw_payload)
        return ""

    def get_message_name(self) -> str:
        candidates = [
            self.message.name if self.message else None,
            self.chat.messagePayload.name if self.chat and self.chat.messagePayload else None,
        ]
        for name in candidates:
            if name:
                return name
        if self.raw_payload:
            msg = self.raw_payload.get("message") or (self.raw_payload.get("chat") or {}).get("messagePayload") or {}
            if isinstance(msg, dict) and msg.get("name"):
                return msg["name"]
        return ""

    def is_in_thread(self) -> bool:
        """
        Determina con certeza si el usuario está interactuando dentro de un hilo secundario.
        - En clics de botones: retorna False (debe continuar en el chat principal).
        - En mensajes de chat: compara el ID del mensaje con el ID del thread.
          Si son iguales, es el chat principal. Si son distintos, es una respuesta en hilo.
        """
        if self.is_button_click():
            return False

        msg_name = self.get_message_name()
        thread_name = self.get_thread_name()

        if not msg_name or not thread_name:
            return False

        msg_id = msg_name.rstrip("/").split("/")[-1]
        thread_id = thread_name.rstrip("/").split("/")[-1]

        return bool(msg_id and thread_id and msg_id != thread_id)

    def is_dm(self) -> bool:
        """Determina si la interacción ocurre en un mensaje directo (DM / 1 a 1)."""
        _, space_type = self.get_space()
        if space_type in {"DM", "DIRECT_MESSAGE"}:
            return True
        if self.space and (self.space.singleUserBotDm or self.space.type in {"DM", "DIRECT_MESSAGE"}):
            return True
        if self.chat and self.chat.space and (self.chat.space.singleUserBotDm or self.chat.space.type in {"DM", "DIRECT_MESSAGE"}):
            return True
        if self.raw_payload:
            sp = self.raw_payload.get("space") or (self.raw_payload.get("chat") or {}).get("space") or {}
            if isinstance(sp, dict):
                if sp.get("singleUserBotDm") or sp.get("type") in {"DM", "DIRECT_MESSAGE"}:
                    return True
        # Si no hay indicios de SPACE o ROOM, en Google Chat los bots suelen hablar en DM
        return space_type not in {"SPACE", "ROOM", "GROUP_CHAT"}

    def is_thread_reply(self) -> bool:
        """Indica si el usuario respondió explícitamente dentro de un hilo secundario."""
        if self.message and self.message.threadReply:
            return True
        if self.chat and self.chat.messagePayload and self.chat.messagePayload.threadReply:
            return True
        if self.raw_payload:
            msg = self.raw_payload.get("message") or (self.raw_payload.get("chat") or {}).get("messagePayload") or {}
            if isinstance(msg, dict) and msg.get("threadReply"):
                return True
        return False

    def get_action_parameters(self) -> dict[str, str]:
        params = {}
        raw = None
        if self.commonEventObject and self.commonEventObject.parameters:
            raw = self.commonEventObject.parameters
        elif self.action and self.action.parameters:
            raw = self.action.parameters
        elif self.chat and self.chat.actionEvent and self.chat.actionEvent.parameters:
            raw = self.chat.actionEvent.parameters

        if isinstance(raw, dict):
            return {k: str(v) for k, v in raw.items()}
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, ActionParameter):
                    params[item.key] = item.value or ""
                elif isinstance(item, dict) and "key" in item:
                    params[item["key"]] = str(item.get("value", ""))
        return params

    def get_invoked_function(self) -> str:
        if self.commonEventObject and self.commonEventObject.invokedFunction:
            return self.commonEventObject.invokedFunction
        if self.action and self.action.function:
            return self.action.function
        if self.action and self.action.actionMethodName:
            return self.action.actionMethodName
        if self.chat and self.chat.actionEvent:
            return self.chat.actionEvent.function or self.chat.actionEvent.actionMethodName or ""
        return ""

    def is_button_click(self) -> bool:
        return bool(
            self.buttonClickedPayload
            or (self.chat and self.chat.buttonClickedPayload)
            or self.type == "CARD_CLICKED"
            or self.get_invoked_function()
            or self.get_action_parameters()
        )

    def get_attachments(self) -> List[AttachmentSchema]:
        atts: List[AttachmentSchema] = []
        if self.message:
            if self.message.attachment:
                atts.extend(self.message.attachment)
            if self.message.attachments:
                atts.extend(self.message.attachments)
        if self.chat and self.chat.messagePayload:
            if self.chat.messagePayload.attachment:
                atts.extend(self.chat.messagePayload.attachment)
            if self.chat.messagePayload.attachments:
                atts.extend(self.chat.messagePayload.attachments)
        return atts

    def get_text_content(self) -> str:
        """Extrae el contenido textual del mensaje de múltiples estructuras posibles."""
        candidates = [
            self.message.argumentText if self.message else None,
            self.message.text if self.message else None,
            self.chat.messagePayload.argumentText if self.chat and self.chat.messagePayload else None,
            self.chat.messagePayload.text if self.chat and self.chat.messagePayload else None,
        ]

        for c in candidates:
            if c and str(c).strip():
                return str(c).strip()

        # Fallback recursivo sobre todo el JSON recibido
        if self.raw_payload:
            return _extract_text_recursive(self.raw_payload)

        return ""


# Alias de conformidad con auditoría técnica
GoogleChatEventDTO = GoogleChatWebhookEvent
