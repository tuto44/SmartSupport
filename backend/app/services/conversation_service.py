from app.database.mysql_manager import MySQLManager


class ConversationService:

    def __init__(self):
        self.mysql = MySQLManager()

    def crear_conversacion(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        title: str = "Nueva conversación"
    ):
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor()
            sql = """
                INSERT INTO conversations (
                    id, user_id, user_name, title
                ) VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP
            """
            cursor.execute(sql, (conversation_id, user_id, user_name, title))
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def obtener_estado_conversacion(self, conversation_id: str) -> dict:
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            sql = "SELECT root_issue, last_context FROM conversations WHERE id = %s"
            cursor.execute(sql, (conversation_id,))
            return cursor.fetchone() or {}
        finally:
            cursor.close()
            connection.close()

    def actualizar_estado_conversacion(
        self,
        conversation_id: str,
        root_issue: str | None = None,
        last_context: str | None = None
    ):
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor()
            campos = []
            valores = []

            if root_issue is not None:
                campos.append("root_issue = %s")
                valores.append(root_issue)

            if last_context is not None:
                campos.append("last_context = %s")
                valores.append(last_context)

            if campos:
                valores.append(conversation_id)
                sql = f"UPDATE conversations SET {', '.join(campos)} WHERE id = %s"
                cursor.execute(sql, tuple(valores))
                connection.commit()
                print(f"[MYSQL] Estado actualizado para {conversation_id} (filas: {cursor.rowcount})")
        finally:
            cursor.close()
            connection.close()

    def obtener_historial(
        self,
        conversation_id: str,
        limite: int = 8
    ) -> list:
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            sql = """
                SELECT role, content
                FROM chat_history
                WHERE conversation_id = %s
                ORDER BY id DESC
                LIMIT %s
            """
            cursor.execute(sql, (conversation_id, limite))
            mensajes = cursor.fetchall()
            mensajes.reverse()
            return mensajes
        finally:
            cursor.close()
            connection.close()

    def agregar_mensaje(
        self,
        conversation_id: str,
        user_id: str,
        user_name: str,
        rol: str,
        mensaje: str
    ):
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor()

            # Asegurar o refrescar conversación
            title = (
                mensaje[:30] + "..."
                if rol == "user" and mensaje
                else "Nueva conversación"
            )
            sql_conv = """
                INSERT INTO conversations (
                    id, user_id, user_name, title
                ) VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP
            """
            cursor.execute(sql_conv, (conversation_id, user_id, user_name, title))

            # Insertar mensaje en historial
            sql_msg = """
                INSERT INTO chat_history (
                    conversation_id, user_name, role, content
                ) VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql_msg, (conversation_id, user_name, rol, mensaje))
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def obtener_conversaciones(self, user_name: str) -> list:
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor(dictionary=True)
            sql = """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE user_name = %s
                ORDER BY updated_at DESC
            """
            cursor.execute(sql, (user_name,))
            return cursor.fetchall()
        finally:
            cursor.close()
            connection.close()

    def eliminar_conversacion(self, conversation_id: str):
        connection = self.mysql.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM chat_history WHERE conversation_id = %s", (conversation_id,))
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            connection.commit()
            print(f"[MYSQL] Conversación {conversation_id} eliminada por reinicio de contexto.")
        finally:
            cursor.close()
            connection.close()