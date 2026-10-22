import mysql.connector
from mysql.connector import Error, pooling

from app.config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD
)


class MySQLManager:
    _pool: pooling.MySQLConnectionPool | None = None
    _tablas_inicializadas: bool = False

    def __init__(self):
        self.config = {
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "database": MYSQL_DATABASE,
            "user": MYSQL_USER,
            "password": MYSQL_PASSWORD,
            "charset": "utf8mb4",
            "collation": "utf8mb4_unicode_ci",
            "use_unicode": True
        }
        self._inicializar_pool()
        self._asegurar_tablas()

    def _inicializar_pool(self):
        if MySQLManager._pool is None:
            try:
                MySQLManager._pool = pooling.MySQLConnectionPool(
                    pool_name="smartsupport_pool",
                    pool_size=5,
                    pool_reset_session=True,
                    **self.config
                )
                print("[MYSQL] Connection Pool inicializado con éxito.")
            except Error as e:
                print(f"[MYSQL ERROR] Falló la creación del Connection Pool: {e}")
                MySQLManager._pool = None

    def _asegurar_tablas(self):
        """Crea y actualiza la estructura de tablas para soportar el flujo de objetivos y emojis."""
        if MySQLManager._tablas_inicializadas:
            return

        crear_conversations = """
            CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR(64) NOT NULL,
                user_id VARCHAR(128) NOT NULL,
                user_name VARCHAR(255) NOT NULL,
                title VARCHAR(255) DEFAULT 'Nueva conversación',
                root_issue TEXT NULL,
                last_context MEDIUMTEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """

        crear_chat_history = """
            CREATE TABLE IF NOT EXISTS chat_history (
                id BIGINT AUTO_INCREMENT NOT NULL,
                conversation_id VARCHAR(64) NOT NULL,
                user_name VARCHAR(255) NOT NULL,
                role VARCHAR(32) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                INDEX idx_conversation (conversation_id),
                CONSTRAINT fk_chat_history_conversation
                    FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """

        connection = None
        try:
            connection = self.get_connection()
            cursor = connection.cursor()
            cursor.execute(crear_conversations)
            cursor.execute(crear_chat_history)

            # Migración automática si la tabla ya existía sin las nuevas columnas
            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN root_issue TEXT NULL AFTER title;")
            except Exception:
                pass

            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN last_context MEDIUMTEXT NULL AFTER root_issue;")
            except Exception:
                pass

            connection.commit()
            cursor.close()
            MySQLManager._tablas_inicializadas = True
            print("[MYSQL] Tablas y columnas verificadas correctamente.")
        except Exception as e:
            print(f"[MYSQL AVISO] Verificación de tablas en arranque omitida o con error: {e}")
        finally:
            if connection and connection.is_connected():
                connection.close()

    def get_connection(self):
        try:
            if MySQLManager._pool:
                return MySQLManager._pool.get_connection()

            connection = mysql.connector.connect(**self.config)
            if connection.is_connected():
                return connection

            raise ConnectionError("No se pudo establecer conexión con MySQL.")

        except Error as e:
            raise ConnectionError(f"Error conectando con MySQL: {e}") from e

    def test_connection(self) -> bool:
        connection = None
        try:
            connection = self.get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            return result[0] == 1
        except Exception:
            return False
        finally:
            if connection and connection.is_connected():
                connection.close()