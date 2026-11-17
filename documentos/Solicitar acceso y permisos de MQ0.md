# Guía para Solicitar Permisos y Transacciones en MQ0

## Contexto y Prerrequisitos
Para solicitar permisos en el sistema MQ0, es necesario contar con acceso previo al sistema. Esto requiere que el encargado de TI configure la conexión en SAP y que la solicitud de acceso sea concedida a través del portal `wpass`. 

Si aún no cuentas con acceso a MQ0, debes seguir el procedimiento detallado en el Paso 1. Si ya dispones de acceso, puedes pasar directamente al Paso 2.

---

## Paso 1: Solicitar Acceso a MQ0 (vía wpass)

1. Ingresa al portal wpass: [https://access.whirlpool.com/wpass/wpass/](https://access.whirlpool.com/wpass/wpass/)
2. En el panel principal, haz clic en **Solicitar acceso**.
3. En el panel lateral izquierdo, desplázate hacia abajo hasta encontrar **LAR SAP**.
4. Selecciona **LAR SAP** y, entre las opciones desplegadas, elige **ECC**.
5. Busca el permiso denominado **MQ0**.
   - *Nota:* Puedes verificar si ya dispones de este acceso; de ser así, aparecerá el mensaje «Ya concedido».
   - Si no cuentas con él, haz clic en **Añadir al carrito**.
6. Dirígete a **Mi carrito**.
7. Haz clic en **Revisa**, ingresa la justificación correspondiente y selecciona nuevamente **Revisa** para confirmar.
8. Espera a que la solicitud sea aprobada.

---

## Paso 2: Solicitar Transacciones Específicas (vía Service NOW)

Una vez validado o concedido el acceso general a MQ0, debes solicitar las transacciones específicas requeridas a través del portal Service NOW.

1. Ingresa al portal de Service NOW: [https://whirlpool.service-now.com/sp](https://whirlpool.service-now.com/sp)
2. En el panel principal, selecciona **IT Service Catalog**.
3. En el buscador, escribe `IT Ad Hoc Request` y selecciona la primera opción que aparezca.
4. Completa el formulario que se desplegará con los siguientes datos:
   - **Método de contacto:** Selecciona "email".
   - **What application is this request about?:** Escribe "MQ0".
   - **Descripción breve:** Indica brevemente que necesitas un permiso para MQ0 (*Nota importante: Debe redactarse en inglés*).
   - **Descripción detallada:** Explica detalladamente los permisos requeridos e incluye la lista exacta de transacciones o accesos necesarios (*Nota importante: Debe redactarse en inglés*).
5. Haz clic en **Enviar** y queda a la espera de la resolución del ticket.

> **Nota importante para RAG / Asistente Virtual:** Tanto la descripción breve como la detallada en el formulario de Service NOW del Paso 2 **deben estar escritas obligatoriamente en inglés**.