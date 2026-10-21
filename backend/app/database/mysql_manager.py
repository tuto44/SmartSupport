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

    def __init__(self):
        self.config = {
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "database": MYSQL_DATABASE,
            "user": MYSQL_USER,
            "password": MYSQL_PASSWORD
        }
        self._inicializar_pool()

    def _inicializar_pool(self):
        if MySQLManager._pool is None:
            try:
                MySQLManager._pool = pooling.MySQLConnectionPool(
                    pool_name="smartsupport_pool",
                    pool_size=5,
                    pool_reset_session=True,
                    **self.config
                )
            except Error as e:
                print(f"Error inicializando Connection Pool de MySQL: {e}")
                MySQLManager._pool = None

    def get_connection(self):
        try:
            if MySQLManager._pool:
                return MySQLManager._pool.get_connection()

            # Fallback en caso de que el pool no esté inicializado
            connection = mysql.connector.connect(**self.config)
            if connection.is_connected():
                return connection

            raise ConnectionError(
                "No se pudo establecer conexión con MySQL."
            )

        except Error as e:
            raise ConnectionError(
                f"Error conectando con MySQL: {e}"
            ) from e

    def test_connection(self):
        connection = None

        try:
            connection = self.get_connection()

            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

            return result[0] == 1

        finally:
            if connection and connection.is_connected():
                connection.close()