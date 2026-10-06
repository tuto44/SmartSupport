import mysql.connector
from mysql.connector import Error

from app.config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_DATABASE,
    MYSQL_USER,
    MYSQL_PASSWORD
)


class MySQLManager:

    def __init__(self):
        self.config = {
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "database": MYSQL_DATABASE,
            "user": MYSQL_USER,
            "password": MYSQL_PASSWORD
        }

    def get_connection(self):
        try:
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