from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field, model_validator


class UserSchema(BaseModel):
    name: Optional[str] = None
    displayName: Optional[str] = None
    type: Optional[str] = None


class SpaceSchema(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    displayName: Optional[str] = None


class ThreadSchema(BaseModel):
    name: Optional[str] = None


class AttachmentDataRef(BaseModel):
    resourceName: Optional[str] = None


class AttachmentSchema(BaseModel):
    name: Optional[str] = None
    contentType: Optional[str] = None
    attachmentDataRef: Optional[AttachmentDataRef] = None


class MessagePayloadSchema(BaseModel):
    name: Optional[str] = None
    text: Optional[str] = None
    argumentText: Optional[str] = None
    sender: Optional[UserSchema] = None
    thread: Optional[ThreadSchema] = None
    space: Optional[SpaceSchema] = None
    attachment: Optional[List[AttachmentSchema]] = None
    attachments: Optional[List[AttachmentSchema]] = None


class ActionParameter(BaseModel):
    key: str
    value: Optional[str] = None


class CommonEventObjectSchema(BaseModel):
    invokedFunction: Optional[str] = None
    parameters: Optional[Union[dict[str, Any], List[ActionParameter]]] = None


class ActionEventSchema(BaseModel):
    function: Optional[str] = None
    actionMethodName: Optional[str] = None
    parameters: Optional[Union[dict[str, Any], List[ActionParameter]]] = None


class NestedChatObject(BaseModel):
    user: Optional[UserSchema] = None
    space: Optional[SpaceSchema] = None
    messagePayload: Optional[MessagePayloadSchema] = None
    buttonClickedPayload: Optional[dict[str, Any]] = None
    actionEvent: Optional[ActionEventSchema] = None


class GoogleChatWebhookEvent(BaseModel):
    type: Optional[str] = None
    user: Optional[UserSchema] = None
    space: Optional[SpaceSchema] = None
    message: Optional[MessagePayloadSchema] = None
    thread: Optional[ThreadSchema] = None
    chat: Optional[NestedChatObject] = None
    buttonClickedPayload: Optional[dict[str, Any]] = None
    commonEventObject: Optional[CommonEventObjectSchema] = None
    action: Optional[ActionEventSchema] = None

    def get_user_display_name(self) -> str:
        candidates = [
            self.chat.user.displayName if self.chat and self.chat.user else None,
            self.chat.user.name if self.chat and self.chat.user else None,
            self.user.displayName if self.user else None,
            self.user.name if self.user else None,
            self.message.sender.displayName if self.message and self.message.sender else None,
            self.message.sender.name if self.message and self.message.sender else None,
        ]
        for name in candidates:
            if name:
                return name
        return "Usuario Google Chat"

    def get_user_id(self) -> str:
        candidates = [
            self.chat.user.name if self.chat and self.chat.user else None,
            self.user.name if self.user else None,
            self.message.sender.name if self.message and self.message.sender else None,
        ]
        for uid in candidates:
            if uid:
                return uid
        return self.get_user_display_name()

    def get_space(self) -> tuple[str, str]:
        """Retorna (space_name, space_type)."""
        candidates = [
            self.chat.space if self.chat else None,
            self.space,
            self.message.space if self.message else None,
        ]
        for sp in candidates:
            if sp and sp.name:
                return sp.name, sp.type or ""
        return "", ""

    def get_thread_name(self) -> str:
        candidates = [
            self.message.thread.name if self.message and self.message.thread else None,
            self.thread.name if self.thread else None,
        ]
        for th in candidates:
            if th:
                return th
        return ""

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
        return atts

    def get_text_content(self) -> str:
        if self.message:
            return (self.message.argumentText or self.message.text or "").strip()
        return ""


# Alias de conformidad con auditoría técnica
GoogleChatEventDTO = GoogleChatWebhookEvent
