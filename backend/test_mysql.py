from app.database.mysql_manager import MySQLManager


def main():
    print("=" * 60)
    print("PRUEBA DE CONEXIÓN MYSQL")
    print("=" * 60)

    mysql = MySQLManager()

    if mysql.test_connection():
        print("Conexión a MySQL exitosa.")
    else:
        print("No se pudo conectar a MySQL.")


if __name__ == "__main__":
    main()