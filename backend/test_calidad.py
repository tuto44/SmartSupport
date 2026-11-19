import asyncio
import re
from app.core.database import SessionLocal
from app.repositories.implementations.mysql_conversation_repository import MySQLConversationRepository
from app.repositories.implementations.qdrant_vector_repository import QdrantVectorRepository
from app.services.implementations.gemini_llm_service import GeminiLLMService
from app.services.rag_service import RagService
from app.utils.format_utils import formatear_para_google_chat

CASOS_PRUEBA = [
    {
        "id": 1,
        "nombre": "1. Permisos de SAP en WPASS — Sin contaminación MQ0 (Flujo Multi-turno)",
        "conv_id": "test_qa_wpass_01",
        "turnos": [
            "Necesito un permiso de SAP",
            "Listo, ya ingresé"
        ],
    },
    {
        "id": 2,
        "nombre": "2. ServiceNow - Transacciones de MQ0 (Requerimiento)",
        "conv_id": "test_qa_snow_01",
        "turnos": [
            "Necesito que me habiliten una transacción específica en MQ0, ¿cómo la pido?"
        ],
    },
    {
        "id": 3,
        "nombre": "3. Falla SAP en oficina + Encadenamiento WPASS",
        "conv_id": "test_qa_vpn_01",
        "turnos": [
            "Estoy en la oficina y no me abre SAP, ¿qué hago?"
        ],
    },
    {
        "id": 4,
        "nombre": "4. Temas Locales HWI Separados (Windows vs Impresora)",
        "conv_id": "test_qa_hwi_01",
        "turnos": [
            "Se me bloqueó la clave de Windows del portátil y tampoco tengo la clave para imprimir"
        ],
    },
    {
        "id": 5,
        "nombre": "5. Anti-alucinación fuera de manuales (iPhone)",
        "conv_id": "test_qa_ooc_01",
        "turnos": [
            "¿Cómo configuro la impresora en mi celular personal iPhone?"
        ],
    },
]


def validar_checks_caso(caso_id: int, turno_idx: int, salida_gchat: str) -> dict:
    salida_lower = salida_gchat.lower()
    fuga_cot = "<razonamiento>" in salida_lower
    url_rota = bool(re.search(r"\*+https?://", salida_gchat))

    checks = {
        "CoT limpio": not fuga_cot,
        "URL intacta": not url_rota,
    }

    if caso_id == 1:
        if turno_idx == 1:
            checks["URL WPASS completa"] = "access.whirlpool.com/wpass" in salida_lower
            checks["Sin mención MQ0 (Turno 1)"] = "mq0" not in salida_lower
            checks["Sin mención ServiceNow (Turno 1)"] = "service-now" not in salida_lower and "servicenow" not in salida_lower
            checks["Paso 1 único (no 8 pasos)"] = (
                "paso 8" not in salida_lower
                and "8." not in salida_gchat
                and "paso 7" not in salida_lower
            )
        elif turno_idx == 2:
            checks["No cierre prematuro"] = not any(
                frase in salida_lower
                for frase in (
                    "me alegra mucho que hayas podido resolver",
                    "si en el futuro requieres soporte",
                    "si en el futuro tienes otra consulta",
                    "que tengas un excelente día",
                    "problema resuelto",
                )
            )
            checks["Sin mención MQ0 (Turno 2)"] = "mq0" not in salida_lower
            checks["Sin mención ServiceNow (Turno 2)"] = "service-now" not in salida_lower and "servicenow" not in salida_lower
            checks["Avanza a Paso 2 (Solicitar acceso)"] = any(
                k in salida_lower
                for k in [
                    "solicitar acceso", "lar sap", "paso 2", "panel", "carrito",
                    "opción", "búsqueda", "busqueda", "buscar", "permiso", "cesta", "modelo"
                ]
            )

    elif caso_id == 2:
        checks["Menciona ServiceNow"] = any(
            k in salida_lower for k in ["servicenow", "service-now", "service now"]
        )
        checks["Clasifica Requerimiento"] = (
            "requerimiento" in salida_lower or "request" in salida_lower
        )
        checks["Ruta Ad Hoc Request"] = any(
            k in salida_lower for k in ["ad hoc request", "it service catalog", "ad hoc"]
        )

    elif caso_id == 3:
        checks["VPN Site-to-Site (Oficina)"] = any(
            k in salida_lower
            for k in [
                "site-to-site", "site to site", "automática", "automatica",
                "no requiere vpn", "no debes", "no necesitas", "ya cuenta con",
                "ya estás", "ya estas", "red hwi"
            ]
        )
        checks["Sin mención GlobalProtect"] = (
            "globalprotect" not in salida_lower and "global protect" not in salida_lower
        )
        checks["Encadena con WPASS"] = "wpass" in salida_lower and any(
            k in salida_lower for k in ["contraseña", "resincroniz", "desincroniz", "desbloque", "credenciales"]
        )
        checks["Sin encabezados ## crudos"] = "##" not in salida_gchat
        checks["Sin nota editorial copiada"] = "consulte el manual" not in salida_lower

    elif caso_id == 4:
        checks["Deriva a Encargado TI HWI"] = any(
            k in salida_lower
            for k in ["encargado de ti", "departamento de ti", "ti de hwi", "ti hwi"]
        )
        checks["Diferencia temas independientes"] = any(
            k in salida_lower
            for k in [
                "independiente", "diferente", "ambas", "dos", "separad",
                "por un lado", "respecto a", "clave de windows", "impresora", "distintas"
            ]
        )

    elif caso_id == 5:
        checks["Sin manual documentado"] = any(
            k in salida_lower
            for k in [
                "no se encuentra", "no dispon", "no hay manual", "no contamos",
                "no existe", "no está documentad", "no esta documentad", "no dispongo",
                "manual o procedimiento", "procedimiento oficial", "dispositivos personales",
                "no oficial", "soporte local"
            ]
        )
        checks["Deriva a Encargado TI HWI"] = any(
            k in salida_lower
            for k in ["encargado de ti", "departamento de ti", "ti de hwi", "ti hwi"]
        )

    return checks


async def ejecutar_bateria():
    db = SessionLocal()
    repo = MySQLConversationRepository(session=db)
    rag = RagService(
        conversation_repo=repo,
        vector_repo=QdrantVectorRepository(),
        llm_service=GeminiLLMService(),
    )

    todos_los_checks_ok = True

    try:
        for caso in CASOS_PRUEBA:
            conv_id = caso["conv_id"]
            repo.eliminar_conversacion(conv_id)
            db.commit()

            print("=" * 70)
            print(f"CASO: {caso['nombre']}")
            for idx, pregunta in enumerate(caso["turnos"], start=1):
                # Resiliencia ante desconexiones transitorias de red con Google API
                for intento in range(3):
                    try:
                        respuesta, botones = await rag.responder(
                            conversation_id=conv_id,
                            user_id="test_user",
                            user_name="Ricardo",
                            pregunta=pregunta,
                        )
                        break
                    except Exception as error:
                        if intento == 2:
                            raise
                        await asyncio.sleep(2.0 * (intento + 1))

                db.commit()
                salida_gchat = formatear_para_google_chat(respuesta)
                estado = repo.obtener_estado_conversacion(conv_id)

                checks = validar_checks_caso(caso["id"], idx, salida_gchat)
                checks_str = " | ".join(f"{k}: {v}" for k, v in checks.items())

                if not all(checks.values()):
                    todos_los_checks_ok = False

                print(f"\n[Turno {idx}] Usuario: {pregunta}")
                print(f"[Root Issue]: {estado.root_issue}")
                print(f"[Respuesta Google Chat]:\n{salida_gchat}\n")
                print(f"[Checks] {checks_str}")

            # Limpiar conversación de prueba al finalizar
            repo.eliminar_conversacion(conv_id)
            db.commit()

        print("=" * 70)
        if todos_los_checks_ok:
            print("RESULTADO GLOBAL: TODOS LOS CHECKS PASARON EN TRUE")
        else:
            print("RESULTADO GLOBAL: ALGUNOS CHECKS FALLARON")
        print("=" * 70)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(ejecutar_bateria())
