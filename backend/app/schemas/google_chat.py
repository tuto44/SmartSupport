from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GoogleChatUserDTO(BaseModel):
    name: Optional[str] = Field(default=None)
    displayName: Optional[str] = Field(default=None)
    avatarUrl: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)


class GoogleChatSpaceDTO(BaseModel):
    name: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    displayName: Optional[str] = Field(default=None)


class GoogleChatFormActionDTO(BaseModel):
    actionMethodName: Optional[str] = Field(default=None)
    parameters: Optional[List[Dict[str, str]]] = Field(default=None)


class GoogleChatCommonEventDTO(BaseModel):
    invokedFunction: Optional[str] = Field(default=None)
    parameters: Optional[Dict[str, Any]] = Field(default=None)


class GoogleChatEventDTO(BaseModel):
    type: Optional[str] = Field(default=None)
    eventTime: Optional[str] = Field(default=None)
    space: Optional[GoogleChatSpaceDTO] = Field(default=None)
    message: Optional[Dict[str, Any]] = Field(default=None)
    user: Optional[GoogleChatUserDTO] = Field(default=None)
    action: Optional[GoogleChatFormActionDTO] = Field(default=None)
    common: Optional[GoogleChatCommonEventDTO] = Field(default=None)

    def is_button_click(self) -> bool:
        return self.type == "CARD_CLICKED" or self.action is not None or self.common is not None

    def get_user_display_name(self) -> str:
        if self.user and self.user.displayName:
            return self.user.displayName
        if self.message and isinstance(self.message, dict):
            sender = self.message.get("sender")
            if isinstance(sender, dict):
                return sender.get("displayName", "Usuario")
        return "Usuario"

    def get_user_id(self) -> str:
        if self.user and self.user.name:
            return self.user.name
        if self.message and isinstance(self.message, dict):
            sender = self.message.get("sender")
            if isinstance(sender, dict):
                return sender.get("name", "usuario_desconocido")
        return "usuario_desconocido"

    def get_space(self) -> tuple[str, str]:
        # 1. Intentar desde el objeto space directo
        if self.space and self.space.name:
            return self.space.name, self.space.type or "ROOM"
        
        # 2. Intentar buscar dentro del objeto message (común en webhooks de Google Chat)
        if self.message and isinstance(self.message, dict):
            space_data = self.message.get("space")
            if isinstance(space_data, dict):
                return space_data.get("name", ""), space_data.get("type", "ROOM")
            
            # 3. Intentar extraer del campo 'name' del mensaje (ej. spaces/AAAA.../messages/...)
            msg_name = self.message.get("name", "")
            if "/messages/" in msg_name:
                space_part = msg_name.split("/messages/")[0]
                return space_part, "ROOM"

        return "", ""

    def is_dm(self) -> bool:
        _, space_type = self.get_space()
        return space_type in {"DM", "DIRECT_MESSAGE"}

    def get_thread_name(self) -> Optional[str]:
        if self.message and isinstance(self.message, dict) and "thread" in self.message:
            thread_data = self.message["thread"]
            if isinstance(thread_data, dict):
                return thread_data.get("name")
        return None

    def is_in_thread(self) -> bool:
        return bool(self.get_thread_name())

    def get_text_content(self) -> str:
        if self.message and isinstance(self.message, dict):
            # Texto directo o texto argumental
            text = self.message.get("text", "")
            if text:
                return text.strip()
            # Si el mensaje viene formateado con texto argumental
            argumentText = self.message.get("argumentText", "")
            if argumentText:
                return argumentText.strip()
        return ""

    def get_attachments(self) -> List[Any]:
        if not self.message or not isinstance(self.message, dict) or "attachment" not in self.message:
            return []
        return self.message["attachment"]

    def get_invoked_function(self) -> str:
        if self.action and self.action.actionMethodName:
            return self.action.actionMethodName
        if self.common and self.common.invokedFunction:
            return self.common.invokedFunction
        return ""

    def get_action_parameters(self) -> Dict[str, str]:
        params = {}
        if self.action and self.action.parameters:
            for p in self.action.parameters:
                if isinstance(p, dict) and "key" in p and "value" in p:
                    params[p["key"]] = p["value"]
        elif self.common and self.common.parameters:
            for k, v in self.common.parameters.items():
                if isinstance(v, dict) and "stringConfigValue" in v:
                    params[k] = v["stringConfigValue"]
                else:
                    params[k] = str(v)
        return params