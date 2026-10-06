from app.services.conversation_service import ConversationService


def main():

    print("=" * 60)
    print("PRUEBA DE CONVERSATION SERVICE")
    print("=" * 60)

    service = ConversationService()

    conversation_id = "test_conversation_001"
    user_id = "test_user_001"
    user_name = "Ricardo"

    print("\n1. Creando conversación...")

    service.crear_conversacion(
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=user_name,
        title="Prueba SmartSupport"
    )

    print("Conversación creada correctamente.")

    print("\n2. Guardando mensaje del usuario...")

    service.agregar_mensaje(
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=user_name,
        rol="user",
        mensaje="¿Cómo ingreso a Citrix?"
    )

    print("Mensaje del usuario guardado.")

    print("\n3. Guardando respuesta del asistente...")

    service.agregar_mensaje(
        conversation_id=conversation_id,
        user_id=user_id,
        user_name=user_name,
        rol="assistant",
        mensaje="Primero verifica que tengas acceso a Citrix."
    )

    print("Respuesta guardada.")

    print("\n4. Recuperando historial...")

    historial = service.obtener_historial(
        conversation_id=conversation_id
    )

    for mensaje in historial:
        print(
            f"{mensaje['role']}: "
            f"{mensaje['content']}"
        )

    print("\n5. Recuperando conversaciones del usuario...")

    conversaciones = service.obtener_conversaciones(
        user_name=user_name
    )

    for conversacion in conversaciones:
        print(
            f"ID: {conversacion['id']} | "
            f"Título: {conversacion['title']}"
        )

    print("\nPRUEBA FINALIZADA.")


if __name__ == "__main__":
    main()