# Procedimiento para crear tickets en My Whirlpool (Incidentes y Requerimientos)

## I. Objetivo y Alcance
Este procedimiento guía a los usuarios para reportar y crear tickets de incidente o requerimiento a través del portal My Whirlpool, solicitando soporte para sistemas o aplicaciones soportadas por GIS LARN. Aplica para todo usuario que prefiera la opción en línea.

## II. Roles y responsabilidades
| Rol | R (Responsable) | A (Aprobador) | C (Consultado) | I (Informado) |
|---|---|---|---|---|
| **Functional Analyst** | X | X | | X |
| **BRM** | | | X | X |
| **Usuarios de negocio** | X | X | X | |

## III. Vías de contacto para Soporte (Primer Nivel)
Los tickets pueden crearse contactando a la Mesa de Servicio (Service Desk) mediante las siguientes vías:
- **Teléfono:** Ver artículo *KB0030227: Help Desk \ Service Desk Phone Numbers*.
- **Chat:** Ver artículo *KB0021866: Obtaining Service Desk Support via Chat*.
- **Portal en línea:** A través de [My Whirlpool](https://my.whirlpool.com/sp).

---

## IV. Registro de un ticket de soporte (Portal My Whirlpool)

### 1. Acceso al portal
1. Ingrese a la liga del Portal My Whirlpool.
2. Introduzca su usuario y contraseña corporativa, y haga clic en **“Iniciar sesión”**. *(Si requiere cambiar el idioma, seleccione su nombre arriba a la derecha y elija "Change Language").*

### 2. Selección del catálogo
Seleccione la opción **“IT Service Catalog”**.

### 3. Elección del tipo de ticket
- **Para Incidentes (Fallas):** Seleccione “Something’s Broken” (¿Podemos ayudarle?) > **“Submit an incident”**.
- **Para Requerimientos (Nuevas peticiones):** Seleccione “IT Requests” > **“IT Ad Hoc Request”**.

### 4. Llenado del formulario
Complete los datos solicitados con el mayor detalle posible (de preferencia en inglés).
- **Aplicación afectada:** En el campo *What application are you having an issue with?*, ingrese el nombre del sistema (Configuration Item / CI). Si tiene dudas, déjelo en blanco.
- **Descripción detallada:** Proporcione toda la información respondiendo a las *Probing Questions* (preguntas de sondeo) generadas por la mesa de ayuda. 

> **Aviso Importante:** Si se presentan 2 o más incidentes con distinta causa raíz, regístrelos en tickets separados.

### 5. Envío y Notificación
1. Haga clic en **“Submit”** (Enviar) en la parte superior derecha.
2. Identifique el número de ticket generado y adjunte cualquier documento o evidencia necesaria.
3. Comparta el número de ticket al Analista Funcional (FA) responsable o al correo `mdl-GIS_FA_Support@whirlpool.com`. En caso de **emergencias (24x7)**, contacte a `operaciones_it@whirlpool.com`.

---

## V. Seguimiento de un ticket de soporte
1. Inicie sesión en [https://my.whirlpool.com/](https://my.whirlpool.com/).
2. En la parte superior derecha, seleccione **"My Tickets"**.
3. En esta vista podrá revisar el estatus de sus incidentes y requerimientos. Haga doble clic en el número de ticket para ver los detalles y actualizaciones. Toda notificación también llegará a su correo electrónico.

---

## VI. Glosario de Conceptos

- **Incidente:** Interrupción no planificada o reducción en la calidad de un servicio de TI. El sistema cambia de "funcionar" a "fallar". La solución implica reparar y devolver la aplicación a su estado original.
- **Requerimiento (Ad Hoc Request):** Solicitud de cambio, mejora o nuevo comportamiento respecto a la funcionalidad actual (cambio de alcance). Requiere análisis, desarrollo, pruebas, aprobaciones y migración.
- **Service Desk (Mesa de Servicio):** Call center que da soporte de primera mano a sistemas y aplicaciones, y realiza la creación de tickets.
- **Configuration Item (CI):** Título dentro de ServiceNow que identifica a qué sistema o aplicación pertenece el ticket y define qué equipo de soporte es responsable.
- **Tiempos SLA:** 
  - **Response SLA:** Tiempo desde que el ticket se asigna a un grupo hasta que un recurso lo acepta.
  - **Resolution SLA:** Tiempo desde la asignación hasta que el ticket es resuelto (Status "Resolve State" o "Close Complete").
