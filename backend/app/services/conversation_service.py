class ConversationService:

    def __init__(self):
        self.conversations = {}

    def obtener_historial(self, usuario: str):
        return self.conversations.get(usuario, [])

    def agregar_mensaje(self, usuario: str, rol: str, mensaje: str):
        if usuario not in self.conversations:
            self.conversations[usuario] = []

        self.conversations[usuario].append({
            "role": rol,
            "content": mensaje
        })